from __future__ import annotations

import inspect
import socket
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtCore import QUrl

from app.core.config import get_settings
from app.db import create_session_factory, init_db
from app.modules.auth.service import AuthService
from app.modules.auth.models import AuthUser
from app.modules.locks.serial_service import SerialBoardInfo, SerialProvisioningService
from app.modules.locks.service import LockDeviceService
from app.modules.properties.service import PropertyService
from app.services.api_client import SmartLockerApiClient
from app.services.encryption import EncryptionService


class WorkerThread(QThread):
    result_ready = pyqtSignal(object)
    error_occurred = pyqtSignal(str)
    progress_changed = pyqtSignal(object)

    def __init__(self, fn, *args, **kwargs) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:
        try:
            kwargs = dict(self._kwargs)
            if "progress_callback" in inspect.signature(self._fn).parameters:
                kwargs["progress_callback"] = self._emit_progress
            result = self._fn(*self._args, **kwargs)
        except Exception as exc:
            self.error_occurred.emit(str(exc))
            return
        self.result_ready.emit(result)

    def _emit_progress(self, payload) -> None:
        self.progress_changed.emit(payload)


class LoginWidget(QWidget):
    def __init__(self, window: "SmartLockerDesktopWindow") -> None:
        super().__init__()
        self.window = window
        layout = QHBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(24)

        hero = self.window.create_card()
        hero_layout = QVBoxLayout(hero)
        hero_layout.addWidget(self.window.make_title("SmartLocker Desktop"))
        hero_layout.addWidget(
            self.window.make_text(
                "Отдельное Windows-приложение для активации замков.\n\n"
                "1. Подключите плату к компьютеру.\n"
                "2. При необходимости установите драйверы.\n"
                "3. Войдите в аккаунт SmartLocker.\n"
                "4. Определите плату, выберите Wi-Fi сеть и введите пароль.\n"
                "5. Приложение запишет конфигурацию в плату и только потом сохранит замок в сервисе."
            )
        )
        hero_layout.addStretch(1)

        form_card = self.window.create_card()
        form_layout = QVBoxLayout(form_card)
        form_layout.addWidget(self.window.make_title("Вход в аккаунт", 18))
        form_layout.addWidget(self.window.make_text("Используйте подтвержденный аккаунт SmartLocker."))

        self.email_edit = QLineEdit()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)

        fields = QFormLayout()
        fields.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        fields.addRow("Email", self.email_edit)
        fields.addRow("Пароль", self.password_edit)
        form_layout.addLayout(fields)

        login_button = QPushButton("Войти")
        login_button.clicked.connect(self._login)
        drivers_button = QPushButton("Установить драйверы")
        drivers_button.clicked.connect(self.window.install_drivers)
        form_layout.addWidget(login_button)
        form_layout.addWidget(drivers_button)
        form_layout.addWidget(
            self.window.make_text(
                f"Тестовый администратор: {self.window.settings.admin_email}\n"
                f"Пароль по умолчанию: {self.window.settings.admin_password}"
            )
        )
        form_layout.addStretch(1)

        layout.addWidget(hero, 1)
        layout.addWidget(form_card, 1)

    def _login(self) -> None:
        try:
            if self.window.uses_remote_api:
                payload = self.window.api_client.login(
                    email=self.email_edit.text().strip(),
                    password=self.password_edit.text(),
                )
                user_data = payload["user"]
                user = AuthUser(
                    email=str(user_data["email"]),
                    full_name=str(user_data["full_name"]),
                    phone_encrypted="",
                    birth_date_encrypted="",
                    password_hash="",
                    role=str(user_data.get("role", "user")),
                    is_verified=bool(user_data.get("is_verified", False)),
                )
            else:
                user = self.window.auth_service.authenticate(
                    email=self.email_edit.text().strip(),
                    password=self.password_edit.text(),
                )
        except (ValueError, RuntimeError) as exc:
            QMessageBox.critical(self, "Ошибка входа", str(exc))
            return
        self.window.set_user(user)


class MainWidget(QWidget):
    def __init__(self, window: "SmartLockerDesktopWindow") -> None:
        super().__init__()
        self.window = window
        self.house_map: dict[str, str] = {}
        self.door_map: dict[str, dict[str, str]] = {}
        self.detected_board: SerialBoardInfo | None = None
        self.active_worker: WorkerThread | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        top = QHBoxLayout()
        top.addWidget(window.make_title("SmartLocker Desktop"))
        top.addStretch(1)
        logout_button = QPushButton("Выйти")
        logout_button.clicked.connect(window.logout)
        top.addWidget(logout_button)
        root.addLayout(top)

        root.addWidget(window.make_text(f"Аккаунт: {window.user.full_name} ({window.user.email})"))

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        self.activation_tab = self._build_activation_tab()
        self.devices_tab = self._build_devices_tab()
        self.objects_tab = self._build_objects_tab()
        self.lock_test_tab = self._build_lock_test_tab()

        self.tabs.addTab(self.wrap_scroll(self.activation_tab), "Подключение замка")
        self.tabs.addTab(self.wrap_scroll(self.devices_tab), "Мои замки")
        self.tabs.addTab(self.wrap_scroll(self.objects_tab), "Объекты и двери")
        self.tabs.addTab(self.wrap_scroll(self.lock_test_tab), "Тест lock API")

        self.refresh_all()

    def wrap_scroll(self, widget: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidget(widget)
        return area

    def _build_activation_tab(self) -> QWidget:
        page = QWidget()
        layout = QGridLayout(page)
        layout.setSpacing(16)
        layout.setContentsMargins(0, 0, 0, 0)

        left = self.window.create_card()
        right = self.window.create_card()
        layout.addWidget(left, 0, 0, 1, 2)
        layout.addWidget(right, 0, 2)
        layout.setColumnStretch(0, 2)
        layout.setColumnStretch(1, 2)
        layout.setColumnStretch(2, 2)

        left_layout = QVBoxLayout(left)
        left_layout.addWidget(self.window.make_title("Мастер активации замка", 18))
        left_layout.addWidget(self.window.make_text("Определите плату, выберите Wi-Fi сеть и запишите конфигурацию в устройство."))

        actions = QGridLayout()
        self.port_combo = QComboBox()
        self.wifi_combo = QComboBox()
        self.lock_id_edit = QLineEdit()
        self.esp8266_uid_edit = QLineEdit()
        self.esp32_uid_edit = QLineEdit()
        self.device_name_edit = QLineEdit()
        self.wifi_password_edit = QLineEdit()
        self.wifi_password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.door_combo = QComboBox()
        self.board_info_label = self.window.make_text("Плата не определена.")
        self.wifi_hint_label = self.window.make_text("")
        self.wifi_hint_label.setWordWrap(True)

        refresh_ports = QPushButton("Обновить порты")
        refresh_ports.clicked.connect(self.refresh_ports)
        self.refresh_ports_button = refresh_ports
        detect_board = QPushButton("Определить плату")
        detect_board.clicked.connect(self.detect_board_async)
        self.detect_board_button = detect_board
        generate_ids = QPushButton("Сгенерировать ID")
        generate_ids.clicked.connect(self.generate_ids)
        self.generate_ids_button = generate_ids
        refresh_wifi = QPushButton("Найти сети")
        refresh_wifi.clicked.connect(self.refresh_wifi_networks_async)
        self.refresh_wifi_button = refresh_wifi
        activate = QPushButton("Активировать замок")
        activate.clicked.connect(self.activate_lock_async)
        activate.setMinimumHeight(44)
        self.activate_button = activate

        actions.addWidget(QLabel("COM-порт"), 0, 0)
        actions.addWidget(self.port_combo, 1, 0)
        actions.addWidget(refresh_ports, 1, 1)
        actions.addWidget(detect_board, 2, 0)
        actions.addWidget(generate_ids, 2, 1)
        actions.addWidget(self.board_info_label, 3, 0, 1, 2)
        left_layout.addLayout(actions)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.addRow("Общий Lock ID", self.lock_id_edit)
        form.addRow("UID платы ESP8266", self.esp8266_uid_edit)
        form.addRow("UID платы ESP32", self.esp32_uid_edit)
        form.addRow("Название замка", self.device_name_edit)
        form.addRow("Дверь", self.door_combo)

        wifi_row = QHBoxLayout()
        wifi_row.addWidget(self.wifi_combo, 1)
        wifi_row.addWidget(refresh_wifi)
        wifi_widget = QWidget()
        wifi_widget.setLayout(wifi_row)
        form.addRow("Сеть Wi-Fi", wifi_widget)
        form.addRow("Пароль Wi-Fi", self.wifi_password_edit)
        left_layout.addLayout(form)
        left_layout.addWidget(self.wifi_hint_label)
        self.activation_progress = QProgressBar()
        self.activation_progress.setRange(0, 100)
        self.activation_progress.setValue(0)
        left_layout.addWidget(self.activation_progress)
        self.activation_log = QPlainTextEdit()
        self.activation_log.setReadOnly(True)
        self.activation_log.setMinimumHeight(180)
        left_layout.addWidget(self.activation_log)
        left_layout.addWidget(activate)
        left_layout.addStretch(1)

        right_layout = QVBoxLayout(right)
        right_layout.addWidget(self.window.make_title("Важно", 18))
        right_layout.addWidget(
            self.window.make_text(
                "Сеть выбирается из доступных сетей компьютера, пароль вводится вручную.\n\n"
                "На Windows список сетей часто требует включённую геолокацию и иногда запуск от администратора.\n\n"
                "Замок сохраняется в сервисе только после успешной записи в плату."
            )
        )
        location_button = QPushButton("Открыть настройки геолокации")
        location_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("ms-settings:privacy-location")))
        right_layout.addWidget(location_button)
        right_layout.addStretch(1)
        return page

    def _build_devices_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        card = self.window.create_card()
        card_layout = QVBoxLayout(card)
        card_layout.addWidget(self.window.make_title("Привязанные замки", 18))
        self.devices_table = QTableWidget(0, 7)
        self.devices_table.setHorizontalHeaderLabels(
            ["Замок", "Lock ID", "Платы", "Wi-Fi", "Дверь", "Порт", "Обновлено"]
        )
        self.devices_table.horizontalHeader().setStretchLastSection(True)
        self.devices_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.devices_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        card_layout.addWidget(self.devices_table)
        layout.addWidget(card)
        return page

    def _build_objects_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        grid = QGridLayout()
        grid.setSpacing(16)

        house_card = self.window.create_card()
        door_card = self.window.create_card()
        list_card = self.window.create_card()
        grid.addWidget(house_card, 0, 0)
        grid.addWidget(door_card, 0, 1)
        grid.addWidget(list_card, 1, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        house_layout = QVBoxLayout(house_card)
        house_layout.addWidget(self.window.make_title("Новый объект", 18))
        self.house_name_edit = QLineEdit()
        self.house_address_edit = QLineEdit()
        house_form = QFormLayout()
        house_form.addRow("Название дома", self.house_name_edit)
        house_form.addRow("Адрес", self.house_address_edit)
        house_layout.addLayout(house_form)
        add_house = QPushButton("Добавить объект")
        add_house.clicked.connect(self.add_house)
        house_layout.addWidget(add_house)

        door_layout = QVBoxLayout(door_card)
        door_layout.addWidget(self.window.make_title("Новая дверь", 18))
        self.house_combo = QComboBox()
        self.door_name_edit = QLineEdit()
        self.lock_label_edit = QLineEdit()
        self.lock_unit_edit = QLineEdit()
        door_form = QFormLayout()
        door_form.addRow("Объект", self.house_combo)
        door_form.addRow("Название двери", self.door_name_edit)
        door_form.addRow("Замок/контроллер", self.lock_label_edit)
        door_form.addRow("TravelLine unit ID", self.lock_unit_edit)
        door_layout.addLayout(door_form)
        add_door = QPushButton("Добавить дверь")
        add_door.clicked.connect(self.add_door)
        door_layout.addWidget(add_door)

        list_layout = QVBoxLayout(list_card)
        list_layout.addWidget(self.window.make_title("Структура объектов", 18))
        self.objects_table = QTableWidget(0, 5)
        self.objects_table.setHorizontalHeaderLabels(
            ["Объект", "Адрес", "Дверь", "ID двери", "Замок/контроллер"]
        )
        self.objects_table.horizontalHeader().setStretchLastSection(True)
        self.objects_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.objects_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        list_layout.addWidget(self.objects_table)

        layout.addLayout(grid)
        return page

    def _build_lock_test_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        card = self.window.create_card()
        card_layout = QVBoxLayout(card)
        card_layout.addWidget(self.window.make_title("Тестирование lock API", 18))
        card_layout.addWidget(
            self.window.make_text(
                "После активации можно сразу проверить сервер, получить текущий QR "
                "для замка и использовать выданные lock credentials в прошивке."
            )
        )
        self.server_url_label = self.window.make_text(f"Server URL: {self.window.server_base_url}")
        card_layout.addWidget(self.server_url_label)

        form = QFormLayout()
        self.test_lock_id_edit = QLineEdit()
        self.test_api_key_edit = QLineEdit()
        form.addRow("Lock ID", self.test_lock_id_edit)
        form.addRow("API key", self.test_api_key_edit)
        card_layout.addLayout(form)

        actions = QHBoxLayout()
        fill_last_button = QPushButton("Подставить последний lock")
        fill_last_button.clicked.connect(self.fill_last_provisioning)
        health_button = QPushButton("Проверить /health")
        health_button.clicked.connect(self.check_server_health_async)
        qr_button = QPushButton("Получить QR")
        qr_button.clicked.connect(self.fetch_current_qr_async)
        actions.addWidget(fill_last_button)
        actions.addWidget(health_button)
        actions.addWidget(qr_button)
        card_layout.addLayout(actions)

        self.lock_test_result_label = self.window.make_text("Результаты теста пока пусты.")
        self.lock_test_result_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        card_layout.addWidget(self.lock_test_result_label)
        card_layout.addStretch(1)

        layout.addWidget(card)
        return page

    def refresh_all(self) -> None:
        self.refresh_ports()
        self.refresh_wifi_networks()
        self.refresh_objects()
        self.refresh_devices()
        self.fill_last_provisioning()
        self.reset_activation_progress()

    def reset_activation_progress(self) -> None:
        self.activation_progress.setValue(0)
        self.activation_log.clear()

    def update_activation_progress(self, payload) -> None:
        percent = 0
        message = ""
        if isinstance(payload, dict):
            percent = int(payload.get("percent", 0))
            message = str(payload.get("message", "")).strip()
        elif isinstance(payload, tuple) and len(payload) >= 2:
            percent = int(payload[0])
            message = str(payload[1]).strip()
        else:
            message = str(payload).strip()
        self.activation_progress.setValue(max(0, min(100, percent)))
        if message:
            self.activation_log.appendPlainText(message)

    def set_busy(self, busy: bool, message: str = "") -> None:
        for widget in [
            getattr(self, "refresh_ports_button", None),
            getattr(self, "detect_board_button", None),
            getattr(self, "generate_ids_button", None),
            getattr(self, "refresh_wifi_button", None),
            getattr(self, "activate_button", None),
            getattr(self, "port_combo", None),
            getattr(self, "wifi_combo", None),
            getattr(self, "door_combo", None),
        ]:
            if widget is not None:
                widget.setEnabled(not busy)
        if message:
            self.window.show_status(message)

    def _start_worker(self, worker: WorkerThread, *, busy_message: str, on_result, on_error=None, on_progress=None) -> None:
        if self.active_worker is not None and self.active_worker.isRunning():
            QMessageBox.information(self, "Операция", "Подождите завершения текущей операции.")
            return
        self.active_worker = worker
        self.set_busy(True, busy_message)

        def handle_result(result) -> None:
            self.set_busy(False)
            self.active_worker = None
            on_result(result)

        def handle_error(message: str) -> None:
            self.set_busy(False)
            self.active_worker = None
            if on_error is not None:
                on_error(message)
            else:
                QMessageBox.critical(self, "Ошибка", message)

        worker.result_ready.connect(handle_result)
        worker.error_occurred.connect(handle_error)
        if on_progress is not None:
            worker.progress_changed.connect(on_progress)
        worker.finished.connect(lambda: None)
        worker.start()

    def refresh_ports(self) -> None:
        ports = self.window.serial_service.list_ports()
        current = self.port_combo.currentText()
        self.port_combo.clear()
        if ports:
            self.port_combo.addItems([item.port for item in ports])
        else:
            self.port_combo.addItem("Порт не найден")
        if current:
            index = self.port_combo.findText(current)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)
        if self.detected_board and self.detected_board.port not in [item.port for item in ports]:
            self.detected_board = None
            self.board_info_label.setText("Плата не определена.")

    def refresh_wifi_networks(self) -> None:
        networks = self.window.serial_service.list_wifi_networks()
        self._apply_wifi_networks(networks)

    def _apply_wifi_networks(self, networks: list[str]) -> None:
        current = self.wifi_combo.currentText()
        self.wifi_combo.clear()
        self.wifi_combo.setEditable(True)
        self.wifi_combo.addItems(networks)
        if current:
            self.wifi_combo.setCurrentText(current)
        elif networks:
            self.wifi_combo.setCurrentIndex(0)
        if networks:
            self.wifi_hint_label.setText(f"Найдено сетей: {len(networks)}")
            self.window.show_status(f"Найдено Wi-Fi сетей: {len(networks)}")
        else:
            self.wifi_hint_label.setText(
                "Список сетей пуст. На Windows для этого часто нужны включённая геолокация и запуск от администратора. "
                "SSID можно ввести вручную."
            )
            self.window.show_status("Wi-Fi сети не получены автоматически. Можно ввести SSID вручную.")

    def refresh_wifi_networks_async(self) -> None:
        self._start_worker(
            WorkerThread(self.window.serial_service.list_wifi_networks),
            busy_message="Ищем Wi-Fi сети...",
            on_result=self._apply_wifi_networks,
        )

    def refresh_objects(self) -> None:
        if self.window.uses_remote_api:
            house_views = self.window.api_client.list_objects()
        else:
            with self.window.session_factory() as db:
                service = PropertyService(db=db, encryption=self.window.encryption)
                houses = service.list_houses(self.window.user.email)
                house_views = [service.export_house_view(house) for house in houses]

        self.house_map = {f"{house['name']} ({house['address']})": str(house['id']) for house in house_views}
        self.door_map = {}

        self.house_combo.clear()
        self.house_combo.addItems(self.house_map.keys())
        self.door_combo.clear()
        self.door_combo.addItem("Без привязки к двери")

        self.objects_table.setRowCount(0)
        for house in house_views:
            if not house["doors"]:
                row = self.objects_table.rowCount()
                self.objects_table.insertRow(row)
                for col, value in enumerate([house["name"], house["address"], "Нет дверей", "", ""]):
                    self.objects_table.setItem(row, col, QTableWidgetItem(str(value)))
                continue
            for door in house["doors"]:
                label = f"{house['name']} / {door['name']} ({door['door_uid']})"
                self.door_map[label] = {"id": str(door["id"]), "door_uid": str(door["door_uid"])}
                self.door_combo.addItem(label)
                row = self.objects_table.rowCount()
                self.objects_table.insertRow(row)
                for col, value in enumerate([house["name"], house["address"], door["name"], door["door_uid"], door["lock_label"]]):
                    self.objects_table.setItem(row, col, QTableWidgetItem(str(value)))

    def refresh_devices(self) -> None:
        if self.window.uses_remote_api:
            devices = self.window.api_client.list_locks()
        else:
            with self.window.session_factory() as db:
                service = LockDeviceService(db=db, encryption=self.window.encryption)
                devices = service.list_devices(self.window.user.email)

        self.devices_table.setRowCount(0)
        for device in devices:
            boards = []
            if device["esp8266_uid"]:
                boards.append(f"ESP8266: {device['esp8266_uid']}")
            if device["esp32_uid"]:
                boards.append(f"ESP32: {device['esp32_uid']}")
            door_label = "Не привязан"
            if device["door_name"]:
                door_label = f"{device['house_name']} / {device['door_name']}"
            values = [
                device["device_name"],
                device["lock_id"],
                ", ".join(boards) or "UID не задан",
                device["wifi_ssid"],
                door_label,
                device["port_name"],
                device["updated_at"],
            ]
            row = self.devices_table.rowCount()
            self.devices_table.insertRow(row)
            for col, value in enumerate(values):
                self.devices_table.setItem(row, col, QTableWidgetItem(str(value)))

    def fill_last_provisioning(self) -> None:
        provisioning = self.window.last_provisioning
        if not provisioning:
            return
        self.test_lock_id_edit.setText(str(provisioning.get("lock_id", "")))
        self.test_api_key_edit.setText(str(provisioning.get("api_key", "")))
        self.lock_test_result_label.setText("Подставлены данные последней активации.")

    def _lock_test_client(self) -> SmartLockerApiClient:
        return SmartLockerApiClient(self.window.server_base_url)

    def _check_server_health_job(self) -> dict:
        return self._lock_test_client().health()

    def _fetch_current_qr_job(self) -> dict:
        lock_id = self.test_lock_id_edit.text().strip()
        api_key = self.test_api_key_edit.text().strip()
        if not lock_id:
            raise ValueError("Введите Lock ID.")
        if not api_key:
            raise ValueError("Введите API key.")
        return self._lock_test_client().get_lock_current_qr(lock_id=lock_id, api_key=api_key)

    def check_server_health_async(self) -> None:
        def on_result(result: dict) -> None:
            self.lock_test_result_label.setText(
                f"/health OK\nstatus: {result.get('status')}\nenvironment: {result.get('environment')}"
            )
            self.window.show_status("Server /health ответил.")

        self._start_worker(
            WorkerThread(self._check_server_health_job),
            busy_message="Проверяем /health...",
            on_result=on_result,
            on_error=lambda message: QMessageBox.critical(self, "Lock API", message),
        )

    def fetch_current_qr_async(self) -> None:
        def on_result(result: dict) -> None:
            self.lock_test_result_label.setText(
                "\n".join(
                    [
                        "QR получен.",
                        f"door_uid: {result.get('door_uid')}",
                        f"code: {result.get('code')}",
                        f"issued_at: {result.get('issued_at')}",
                        f"expires_at: {result.get('expires_at')}",
                        f"ttl_seconds: {result.get('ttl_seconds')}",
                    ]
                )
            )
            self.window.show_status("Текущий QR получен.")

        self._start_worker(
            WorkerThread(self._fetch_current_qr_job),
            busy_message="Запрашиваем QR...",
            on_result=on_result,
            on_error=lambda message: QMessageBox.critical(self, "Lock API", message),
        )

    def detect_board(self, progress_callback=None) -> None:
        port_name = self.port_combo.currentText().strip()
        if not port_name or port_name == "Порт не найден":
            raise ValueError("Сначала выберите COM-порт.")
        if progress_callback is not None:
            progress_callback({"percent": 10, "message": f"Открываем порт {port_name}..."})
            progress_callback({"percent": 45, "message": "Отправляем identify в плату..."})
        return self.window.serial_service.identify_board(port_name)

    def detect_board_async(self) -> None:
        self.reset_activation_progress()

        def on_result(board: SerialBoardInfo) -> None:
            self.detected_board = board
            firmware = board.firmware_version or "не указана"
            self.board_info_label.setText(f"{board.chip} на {board.port}, firmware: {firmware}")
            self.update_activation_progress({"percent": 100, "message": f"Плата определена: {board.chip}, firmware {firmware}."})
            self.window.show_status(f"Обнаружена плата {board.chip} на {board.port}.")
            self.generate_ids(for_detected_only=True)

        def on_error(message: str) -> None:
            self.detected_board = None
            self.board_info_label.setText("Плата не определена.")
            self.update_activation_progress({"percent": 100, "message": f"Ошибка определения платы: {message}"})
            QMessageBox.critical(
                self,
                "Плата",
                f"Не удалось определить плату.\n\n"
                "Убедитесь, что в устройстве есть provisioning-прошивка SmartLocker.\n"
                f"Детали: {message}",
            )

        self._start_worker(
            WorkerThread(self.detect_board),
            busy_message="Определяем подключённую плату...",
            on_result=on_result,
            on_error=on_error,
            on_progress=self.update_activation_progress,
        )

    def generate_ids(self, for_detected_only: bool = False) -> None:
        if not self.lock_id_edit.text().strip():
            self.lock_id_edit.setText(self.window.serial_service.generate_lock_id())
        if for_detected_only and self.detected_board:
            if self.detected_board.chip == "ESP8266" and not self.esp8266_uid_edit.text().strip():
                self.esp8266_uid_edit.setText(self.window.serial_service.generate_board_uid("ESP8266"))
            if self.detected_board.chip == "ESP32" and not self.esp32_uid_edit.text().strip():
                self.esp32_uid_edit.setText(self.window.serial_service.generate_board_uid("ESP32"))
            return
        if not self.esp8266_uid_edit.text().strip():
            self.esp8266_uid_edit.setText(self.window.serial_service.generate_board_uid("ESP8266"))
        if not self.esp32_uid_edit.text().strip():
            self.esp32_uid_edit.setText(self.window.serial_service.generate_board_uid("ESP32"))

    def add_house(self) -> None:
        try:
            if self.window.uses_remote_api:
                self.window.api_client.create_house(
                    name=self.house_name_edit.text(),
                    address=self.house_address_edit.text(),
                )
            else:
                with self.window.session_factory() as db:
                    service = PropertyService(db=db, encryption=self.window.encryption)
                    service.add_house(
                        self.window.user.email,
                        name=self.house_name_edit.text(),
                        address=self.house_address_edit.text(),
                    )
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка", str(exc))
            return
        self.house_name_edit.clear()
        self.house_address_edit.clear()
        self.refresh_objects()
        self.window.show_status("Объект сохранён.")

    def add_door(self) -> None:
        try:
            if self.window.uses_remote_api:
                self.window.api_client.create_door(
                    house_id=self.house_map.get(self.house_combo.currentText(), ""),
                    name=self.door_name_edit.text(),
                    lock_label=self.lock_label_edit.text(),
                    travelline_unit_id=self.lock_unit_edit.text(),
                )
            else:
                with self.window.session_factory() as db:
                    service = PropertyService(db=db, encryption=self.window.encryption)
                    service.add_door(
                        self.window.user.email,
                        house_id=self.house_map.get(self.house_combo.currentText(), ""),
                        name=self.door_name_edit.text(),
                        lock_label=self.lock_label_edit.text(),
                        travelline_unit_id=self.lock_unit_edit.text(),
                    )
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка", str(exc))
            return
        self.door_name_edit.clear()
        self.lock_label_edit.clear()
        self.lock_unit_edit.clear()
        self.refresh_objects()
        self.window.show_status("Дверь добавлена.")

    def _activate_lock_job(self, progress_callback=None) -> dict[str, object]:
        if self.detected_board is None:
            raise ValueError("Сначала нажмите «Определить плату».")

        if progress_callback is not None:
            progress_callback({"percent": 5, "message": "Проверяем данные активации..."})
        self.generate_ids(for_detected_only=True)
        chip = self.detected_board.chip or ""
        board_uid = self.esp32_uid_edit.text().strip() if chip == "ESP32" else self.esp8266_uid_edit.text().strip()
        wifi_ssid = self.wifi_combo.currentText().strip()

        if not self.lock_id_edit.text().strip():
            raise ValueError("Не заполнен общий Lock ID.")
        if not board_uid:
            raise ValueError(f"Не заполнен UID для платы {chip}.")
        if not wifi_ssid:
            raise ValueError("Выберите Wi-Fi сеть или введите SSID вручную.")
        if not self.wifi_password_edit.text():
            raise ValueError("Введите пароль Wi-Fi.")

        door_uid = self.door_map.get(self.door_combo.currentText(), {}).get("door_uid", "")
        door_id = self.door_map.get(self.door_combo.currentText(), {}).get("id")

        provisioning = None
        if self.window.uses_remote_api:
            if progress_callback is not None:
                progress_callback({"percent": 30, "message": "Сохраняем замок через API..."})
            save_result = self.window.api_client.save_lock(
                lock_id=self.lock_id_edit.text(),
                device_name=self.device_name_edit.text() or self.lock_id_edit.text(),
                wifi_ssid=wifi_ssid,
                wifi_password=self.wifi_password_edit.text(),
                port_name=self.port_combo.currentText(),
                door_id=door_id,
                esp8266_uid=self.esp8266_uid_edit.text(),
                esp32_uid=self.esp32_uid_edit.text(),
            )
            provisioning = save_result.get("provisioning")
        else:
            if progress_callback is not None:
                progress_callback({"percent": 30, "message": "Сохраняем замок в локальной базе..."})
            with self.window.session_factory() as db:
                service = LockDeviceService(db=db, encryption=self.window.encryption)
                device = service.save_device(
                    self.window.user.email,
                    lock_id=self.lock_id_edit.text(),
                    device_name=self.device_name_edit.text() or self.lock_id_edit.text(),
                    wifi_ssid=wifi_ssid,
                    wifi_password=self.wifi_password_edit.text(),
                    port_name=self.port_combo.currentText(),
                    door_id=door_id,
                    esp8266_uid=self.esp8266_uid_edit.text(),
                    esp32_uid=self.esp32_uid_edit.text(),
                )
                provisioning = service.export_provisioning_view(
                    device,
                    api_base_url=self.window.server_base_url,
                )

        if progress_callback is not None:
            progress_callback({"percent": 65, "message": f"Записываем provisioning в {chip}..."})
        response = self.window.serial_service.provision_board(
            port_name=self.detected_board.port,
            chip=chip,
            lock_id=self.lock_id_edit.text().strip(),
            board_uid=board_uid,
            device_name=self.device_name_edit.text().strip() or self.lock_id_edit.text().strip(),
            wifi_ssid=wifi_ssid,
            wifi_password=self.wifi_password_edit.text(),
            owner_email=self.window.user.email,
            door_uid=door_uid,
            api_key=str((provisioning or {}).get("api_key", "")),
            api_base_url=str((provisioning or {}).get("api_base_url", self.window.server_base_url)),
        )
        if progress_callback is not None:
            progress_callback({"percent": 100, "message": "Активация завершена, плата ответила успешно."})

        return {
            "chip": chip,
            "port": self.detected_board.port,
            "response": response,
            "provisioning": provisioning,
        }

    def activate_lock_async(self) -> None:
        self.reset_activation_progress()

        def on_result(result: dict[str, object]) -> None:
            self.window.last_provisioning = (
                result["provisioning"] if isinstance(result.get("provisioning"), dict) else None
            )
            self.refresh_devices()
            self.fill_last_provisioning()
            self.window.show_status(
                f"Плата {result['chip']} активирована на {result['port']}, замок сохранён в сервисе. "
                f"Ответ: {result['response'].get('status', 'ok')}"
            )
            QMessageBox.information(
                self,
                "Активация",
                (
                    f"Конфигурация записана в {result['chip']} и замок сохранён в сервисе.\n\n"
                    f"Lock ID: {result['provisioning']['lock_id']}\n"
                    f"API key: {result['provisioning']['api_key']}\n"
                    f"API URL: {result['provisioning']['api_base_url']}"
                )
                if result.get("provisioning")
                else f"Конфигурация записана в {result['chip']} и замок сохранён в сервисе.",
            )

        def on_error(message: str) -> None:
            self.update_activation_progress({"percent": 100, "message": f"Ошибка активации: {message}"})
            QMessageBox.critical(self, "Активация", message)

        self._start_worker(
            WorkerThread(self._activate_lock_job),
            busy_message="Записываем конфигурацию в ESP и сохраняем замок...",
            on_result=on_result,
            on_error=on_error,
            on_progress=self.update_activation_progress,
        )


class SmartLockerDesktopWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = get_settings()
        self.api_client = (
            SmartLockerApiClient(self.settings.smartlocker_api_base_url)
            if self.settings.smartlocker_api_base_url
            else None
        )
        self.engine = None
        self.session_factory = None
        if self.api_client is None:
            self.engine, self.session_factory = create_session_factory(self.settings.database_url)
            init_db(self.engine, self.settings.database_url)
        self.encryption = EncryptionService(settings=self.settings)
        self.auth_service = (
            AuthService(
                settings=self.settings,
                session_factory=self.session_factory,
                encryption=self.encryption,
            )
            if self.session_factory is not None
            else None
        )
        self.serial_service = SerialProvisioningService()
        self.user = None
        self.last_provisioning: dict[str, str] | None = None

        self.setWindowTitle("SmartLocker Desktop")
        self.resize(1220, 820)
        self.setMinimumSize(1080, 720)
        self.setStyleSheet(self._build_stylesheet())
        self.setStatusBar(QStatusBar())
        self._build_menu()
        self.show_login()

    @property
    def uses_remote_api(self) -> bool:
        return self.api_client is not None

    @property
    def server_base_url(self) -> str:
        if self.api_client is not None:
            return self.api_client.base_url.rstrip("/")
        if self.settings.provisioning_api_base_url:
            return self.settings.provisioning_api_base_url.rstrip("/")
        if self.settings.smartlocker_api_base_url:
            return self.settings.smartlocker_api_base_url.rstrip("/")
        host = self._detect_lan_ip()
        return f"http://{host}:{self.settings.port}"

    @staticmethod
    def _detect_lan_ip() -> str:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("8.8.8.8", 80))
            detected = probe.getsockname()[0]
            if detected:
                return detected
        except OSError:
            pass
        finally:
            probe.close()
        return "127.0.0.1"

    def _build_menu(self) -> None:
        menu = self.menuBar().addMenu("Сервис")
        install_drivers_action = QAction("Установить драйверы", self)
        install_drivers_action.triggered.connect(self.install_drivers)
        menu.addAction(install_drivers_action)

        location_action = QAction("Настройки геолокации", self)
        location_action.triggered.connect(lambda: QDesktopServices.openUrl(QUrl("ms-settings:privacy-location")))
        menu.addAction(location_action)

    def _build_stylesheet(self) -> str:
        return """
        QMainWindow, QWidget { background: #eef3f7; color: #17324a; }
        QMenuBar, QStatusBar { background: #ffffff; }
        QFrame#Card { background: #ffffff; border: 1px solid #d8e3eb; border-radius: 18px; }
        QLabel { font-size: 14px; }
        QLineEdit, QComboBox, QTableWidget {
            background: #f8fbff;
            border: 1px solid #c9d8e4;
            border-radius: 10px;
            padding: 10px;
            min-height: 22px;
        }
        QPushButton {
            background: #0f6a7e;
            color: white;
            border: none;
            border-radius: 10px;
            padding: 10px 14px;
            font-weight: 600;
        }
        QPushButton:hover { background: #0d5c6d; }
        QTabBar::tab {
            background: #dbe7ef;
            padding: 12px 18px;
            border-top-left-radius: 10px;
            border-top-right-radius: 10px;
            margin-right: 4px;
        }
        QTabBar::tab:selected { background: #ffffff; }
        QHeaderView::section {
            background: #dbe7ef;
            border: none;
            padding: 8px;
            font-weight: 600;
        }
        """

    def create_card(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Card")
        return frame

    def make_title(self, text: str, size: int = 22) -> QLabel:
        label = QLabel(text)
        font = QFont("Segoe UI", size)
        font.setBold(True)
        label.setFont(font)
        label.setWordWrap(True)
        return label

    def make_text(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        return label

    def show_status(self, text: str) -> None:
        self.statusBar().showMessage(text, 15000)

    def show_login(self) -> None:
        self.setCentralWidget(LoginWidget(self))
        self.show_status("Войдите в аккаунт SmartLocker.")

    def set_user(self, user) -> None:
        self.user = user
        self.setCentralWidget(MainWidget(self))
        self.show_status("Вход выполнен.")

    def logout(self) -> None:
        self.user = None
        self.show_login()

    def install_drivers(self) -> None:
        script_path = self._app_base_dir() / "scripts" / "install_bundled_drivers.ps1"
        if not script_path.exists():
            QMessageBox.critical(self, "Драйверы", f"Скрипт не найден: {script_path}")
            return
        try:
            subprocess.Popen(
                [
                    "powershell",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script_path),
                ]
            )
        except Exception as exc:
            QMessageBox.critical(self, "Драйверы", str(exc))
            return
        self.show_status("Запущена установка драйверов.")

    @staticmethod
    def _app_base_dir() -> Path:
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            return Path(sys._MEIPASS)
        return Path(__file__).resolve().parent


def main() -> None:
    app = QApplication(sys.argv)
    window = SmartLockerDesktopWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
