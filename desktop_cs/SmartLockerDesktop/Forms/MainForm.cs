using System.Diagnostics;
using SmartLockerDesktop.Config;
using SmartLockerDesktop.Models;
using SmartLockerDesktop.Services;

namespace SmartLockerDesktop.Forms;

public sealed class MainForm : Form
{
    private readonly AppSettings _settings;
    private readonly SmartLockerApiClient _apiClient;
    private readonly SerialProvisioningService _serialService = new();
    private readonly ApiUser _user;

    private readonly StatusStrip _statusStrip = new();
    private readonly ToolStripStatusLabel _statusLabel = new() { Spring = true, TextAlign = ContentAlignment.MiddleLeft };
    private readonly TabControl _tabs = new() { Dock = DockStyle.Fill };

    private readonly ComboBox _portCombo = new() { Width = 180, DropDownStyle = ComboBoxStyle.DropDownList };
    private readonly ComboBox _wifiCombo = new() { Width = 280, DropDownStyle = ComboBoxStyle.DropDown };
    private readonly ComboBox _doorCombo = new() { Width = 360, DropDownStyle = ComboBoxStyle.DropDownList };
    private readonly TextBox _lockIdTextBox = new() { Width = 260 };
    private readonly TextBox _esp8266TextBox = new() { Width = 260 };
    private readonly TextBox _esp32TextBox = new() { Width = 260 };
    private readonly TextBox _deviceNameTextBox = new() { Width = 260 };
    private readonly TextBox _wifiPasswordTextBox = new() { Width = 260, UseSystemPasswordChar = true };
    private readonly Label _boardInfoLabel = new() { AutoSize = true, MaximumSize = new Size(560, 0) };
    private readonly ProgressBar _activationProgress = new() { Width = 560, Height = 18 };
    private readonly TextBox _activationLog = new() { Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Vertical, Width = 560, Height = 180 };

    private readonly DataGridView _locksGrid = new() { Dock = DockStyle.Fill, ReadOnly = true, AllowUserToAddRows = false, AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill };
    private readonly DataGridView _objectsGrid = new() { Dock = DockStyle.Fill, ReadOnly = true, AllowUserToAddRows = false, AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill };

    private readonly TextBox _houseNameTextBox = new() { Width = 260 };
    private readonly TextBox _houseAddressTextBox = new() { Width = 260 };
    private readonly ComboBox _houseCombo = new() { Width = 260, DropDownStyle = ComboBoxStyle.DropDownList };
    private readonly TextBox _doorNameTextBox = new() { Width = 260 };
    private readonly TextBox _lockLabelTextBox = new() { Width = 260 };
    private readonly TextBox _travelLineUnitTextBox = new() { Width = 260 };

    private readonly TextBox _testLockIdTextBox = new() { Width = 320 };
    private readonly TextBox _testApiKeyTextBox = new() { Width = 320 };
    private readonly Label _lockTestResultLabel = new() { AutoSize = true, MaximumSize = new Size(640, 0) };

    private readonly Dictionary<string, string> _houseMap = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, DoorBindingRef> _doorMap = new(StringComparer.OrdinalIgnoreCase);

    private SerialBoardInfo? _detectedBoard;
    private ProvisioningView? _lastProvisioning;
    private bool _initialLoadStarted;

    public MainForm(AppSettings settings, SmartLockerApiClient apiClient, ApiUser user)
    {
        _settings = settings;
        _apiClient = apiClient;
        _user = user;

        Text = $"SmartLocker Desktop - {user.FullName}";
        Width = 1280;
        Height = 840;
        StartPosition = FormStartPosition.CenterParent;

        BuildMenu();
        BuildUi();
    }

    protected override async void OnShown(EventArgs e)
    {
        base.OnShown(e);
        if (_initialLoadStarted)
        {
            return;
        }

        _initialLoadStarted = true;
        await LoadInitialDataAsync();
    }

    private void BuildMenu()
    {
        var menuStrip = new MenuStrip();
        var serviceMenu = new ToolStripMenuItem("Сервис");
        serviceMenu.DropDownItems.Add("Установить драйверы", null, (_, _) => InstallDrivers());
        serviceMenu.DropDownItems.Add("Настройки геолокации", null, (_, _) => OpenLocationSettings());
        serviceMenu.DropDownItems.Add("Выйти", null, (_, _) => Logout());
        menuStrip.Items.Add(serviceMenu);
        MainMenuStrip = menuStrip;
        Controls.Add(menuStrip);
    }

    private void BuildUi()
    {
        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            RowCount = 2,
        };
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));

        _statusStrip.Items.Add(_statusLabel);
        _tabs.TabPages.Add(new TabPage("Подключение замка") { Controls = { BuildActivationTab() } });
        _tabs.TabPages.Add(new TabPage("Мои замки") { Controls = { BuildLocksTab() } });
        _tabs.TabPages.Add(new TabPage("Объекты и двери") { Controls = { BuildObjectsTab() } });
        _tabs.TabPages.Add(new TabPage("Тест lock API") { Controls = { BuildLockTestTab() } });

        root.Controls.Add(_tabs, 0, 0);
        root.Controls.Add(_statusStrip, 0, 1);
        Controls.Add(root);
    }

    private Control BuildActivationTab()
    {
        var page = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, Padding = new Padding(12) };
        page.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 68));
        page.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 32));

        var left = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.TopDown,
            WrapContents = false,
            AutoScroll = true,
        };
        left.Controls.Add(new Label { Text = "Мастер активации замка", Font = new Font("Segoe UI", 16, FontStyle.Bold), AutoSize = true });
        left.Controls.Add(new Label { Text = "Определите плату, выберите Wi-Fi и запишите provisioning в устройство.", AutoSize = true, MaximumSize = new Size(680, 0) });

        left.Controls.Add(BuildPortRow());
        left.Controls.Add(BuildDetectRow());
        left.Controls.Add(_boardInfoLabel);
        left.Controls.Add(LabeledField("Общий Lock ID", _lockIdTextBox));
        left.Controls.Add(LabeledField("UID платы ESP8266", _esp8266TextBox));
        left.Controls.Add(LabeledField("UID платы ESP32", _esp32TextBox));
        left.Controls.Add(LabeledField("Название замка", _deviceNameTextBox));
        left.Controls.Add(LabeledField("Дверь", _doorCombo));
        left.Controls.Add(BuildWifiRow());
        left.Controls.Add(LabeledField("Пароль Wi-Fi", _wifiPasswordTextBox));
        left.Controls.Add(_activationProgress);
        left.Controls.Add(_activationLog);

        var activateButton = new Button { Text = "Активировать замок", Width = 220, Height = 42 };
        activateButton.Click += async (_, _) => await ActivateLockAsync();
        left.Controls.Add(activateButton);

        var right = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.TopDown,
            WrapContents = false,
            AutoScroll = true,
        };
        right.Controls.Add(new Label { Text = "Важно", Font = new Font("Segoe UI", 16, FontStyle.Bold), AutoSize = true });
        right.Controls.Add(new Label
        {
            Text =
                "Новый клиент работает через API, поэтому данные замков, дверей и аккаунтов всегда синхронизированы с сервером.\n\n" +
                "Список Wi-Fi на Windows может требовать включённую геолокацию. Если сетей нет, SSID можно ввести вручную.",
            AutoSize = true,
            MaximumSize = new Size(320, 0),
        });

        page.Controls.Add(left, 0, 0);
        page.Controls.Add(right, 1, 0);
        return page;
    }

    private Control BuildPortRow()
    {
        var row = new FlowLayoutPanel { AutoSize = true };
        var refreshPortsButton = new Button { Text = "Обновить порты" };
        refreshPortsButton.Click += async (_, _) => await RunUiTaskAsync("Обновляем COM-порты...", async () =>
        {
            ApplyPorts(await Task.Run(_serialService.ListPorts));
        });
        row.Controls.Add(new Label { Text = "COM-порт", AutoSize = true, Margin = new Padding(3, 10, 3, 3) });
        row.Controls.Add(_portCombo);
        row.Controls.Add(refreshPortsButton);
        return row;
    }

    private Control BuildDetectRow()
    {
        var row = new FlowLayoutPanel { AutoSize = true };
        var detectButton = new Button { Text = "Определить плату" };
        detectButton.Click += async (_, _) => await DetectBoardAsync();
        var generateButton = new Button { Text = "Сгенерировать ID" };
        generateButton.Click += (_, _) => GenerateIds();
        row.Controls.Add(detectButton);
        row.Controls.Add(generateButton);
        return row;
    }

    private Control BuildWifiRow()
    {
        var row = new FlowLayoutPanel { AutoSize = true };
        var refreshWifiButton = new Button { Text = "Найти сети" };
        refreshWifiButton.Click += async (_, _) => await RunUiTaskAsync("Ищем Wi-Fi сети...", async () =>
        {
            ApplyWifiNetworks(await Task.Run(_serialService.ListWifiNetworks));
        });
        row.Controls.Add(new Label { Text = "Wi-Fi", AutoSize = true, Margin = new Padding(3, 10, 3, 3) });
        row.Controls.Add(_wifiCombo);
        row.Controls.Add(refreshWifiButton);
        return row;
    }

    private Control BuildLocksTab()
    {
        var panel = new Panel { Dock = DockStyle.Fill, Padding = new Padding(12) };
        _locksGrid.Columns.Add("deviceName", "Замок");
        _locksGrid.Columns.Add("lockId", "Lock ID");
        _locksGrid.Columns.Add("boards", "Платы");
        _locksGrid.Columns.Add("wifi", "Wi-Fi");
        _locksGrid.Columns.Add("door", "Дверь");
        _locksGrid.Columns.Add("port", "Порт");
        _locksGrid.Columns.Add("updated", "Обновлено");
        panel.Controls.Add(_locksGrid);
        return panel;
    }

    private Control BuildObjectsTab()
    {
        var page = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 2, Padding = new Padding(12) };
        page.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
        page.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
        page.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        page.RowStyles.Add(new RowStyle(SizeType.Percent, 100));

        var houseBox = new GroupBox { Text = "Новый объект", Dock = DockStyle.Fill };
        var houseFlow = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.TopDown, WrapContents = false, AutoScroll = true };
        houseFlow.Controls.Add(LabeledField("Название дома", _houseNameTextBox));
        houseFlow.Controls.Add(LabeledField("Адрес", _houseAddressTextBox));
        var addHouseButton = new Button { Text = "Добавить объект" };
        addHouseButton.Click += async (_, _) => await AddHouseAsync();
        houseFlow.Controls.Add(addHouseButton);
        houseBox.Controls.Add(houseFlow);

        var doorBox = new GroupBox { Text = "Новая дверь", Dock = DockStyle.Fill };
        var doorFlow = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.TopDown, WrapContents = false, AutoScroll = true };
        doorFlow.Controls.Add(LabeledField("Объект", _houseCombo));
        doorFlow.Controls.Add(LabeledField("Название двери", _doorNameTextBox));
        doorFlow.Controls.Add(LabeledField("Замок/контроллер", _lockLabelTextBox));
        doorFlow.Controls.Add(LabeledField("TravelLine unit ID", _travelLineUnitTextBox));
        var addDoorButton = new Button { Text = "Добавить дверь" };
        addDoorButton.Click += async (_, _) => await AddDoorAsync();
        doorFlow.Controls.Add(addDoorButton);
        doorBox.Controls.Add(doorFlow);

        _objectsGrid.Columns.Add("house", "Объект");
        _objectsGrid.Columns.Add("address", "Адрес");
        _objectsGrid.Columns.Add("door", "Дверь");
        _objectsGrid.Columns.Add("doorUid", "ID двери");
        _objectsGrid.Columns.Add("lockLabel", "Замок/контроллер");

        page.Controls.Add(houseBox, 0, 0);
        page.Controls.Add(doorBox, 1, 0);
        page.Controls.Add(_objectsGrid, 0, 1);
        page.SetColumnSpan(_objectsGrid, 2);
        return page;
    }

    private Control BuildLockTestTab()
    {
        var panel = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.TopDown,
            WrapContents = false,
            Padding = new Padding(12),
            AutoScroll = true,
        };
        panel.Controls.Add(new Label { Text = "Тестирование lock API", Font = new Font("Segoe UI", 16, FontStyle.Bold), AutoSize = true });
        panel.Controls.Add(new Label { Text = $"Server URL: {_settings.ProvisioningApiBaseUrl}", AutoSize = true });
        panel.Controls.Add(LabeledField("Lock ID", _testLockIdTextBox));
        panel.Controls.Add(LabeledField("API key", _testApiKeyTextBox));

        var row = new FlowLayoutPanel { AutoSize = true };
        var fillButton = new Button { Text = "Подставить последний lock" };
        fillButton.Click += (_, _) => FillLastProvisioning();
        var healthButton = new Button { Text = "Проверить /health" };
        healthButton.Click += async (_, _) => await CheckHealthAsync();
        var qrButton = new Button { Text = "Получить QR" };
        qrButton.Click += async (_, _) => await FetchCurrentQrAsync();
        row.Controls.Add(fillButton);
        row.Controls.Add(healthButton);
        row.Controls.Add(qrButton);
        panel.Controls.Add(row);
        panel.Controls.Add(_lockTestResultLabel);
        return panel;
    }

    private static Control LabeledField(string label, Control control)
    {
        var panel = new FlowLayoutPanel { AutoSize = true, FlowDirection = FlowDirection.TopDown, WrapContents = false };
        panel.Controls.Add(new Label { Text = label, AutoSize = true });
        panel.Controls.Add(control);
        return panel;
    }

    private async Task LoadInitialDataAsync()
    {
        await RunUiTaskAsync("Загружаем данные SmartLocker...", async () =>
        {
            var portsTask = Task.Run(_serialService.ListPorts);
            var wifiTask = Task.Run(_serialService.ListWifiNetworks);
            var housesTask = _apiClient.ListObjectsAsync();
            var locksTask = _apiClient.ListLocksAsync();

            await Task.WhenAll(portsTask, wifiTask, housesTask, locksTask);
            ApplyPorts(await portsTask);
            ApplyWifiNetworks(await wifiTask);
            ApplyObjects(await housesTask);
            ApplyLocks(await locksTask);
            GenerateIds();
        });
    }

    private async Task DetectBoardAsync()
    {
        ResetActivationProgress();
        var portName = _portCombo.SelectedItem?.ToString();
        if (string.IsNullOrWhiteSpace(portName))
        {
            MessageBox.Show(this, "Сначала выберите COM-порт.", "Плата", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }

        await RunUiTaskAsync($"Определяем плату на {portName}...", async () =>
        {
            UpdateActivationProgress(10, $"Открываем порт {portName}...");
            _detectedBoard = await Task.Run(() => _serialService.IdentifyBoard(portName));
            _boardInfoLabel.Text = $"{_detectedBoard.Chip} на {_detectedBoard.Port}, firmware: {_detectedBoard.FirmwareVersion ?? "не указана"}";
            UpdateActivationProgress(100, $"Плата определена: {_detectedBoard.Chip}, firmware {_detectedBoard.FirmwareVersion ?? "не указана"}.");
            GenerateIds(detectedOnly: true);
        });
    }

    private void GenerateIds(bool detectedOnly = false)
    {
        if (string.IsNullOrWhiteSpace(_lockIdTextBox.Text))
        {
            _lockIdTextBox.Text = _serialService.GenerateLockId();
        }

        if (detectedOnly && _detectedBoard is not null)
        {
            if (_detectedBoard.Chip == "ESP8266" && string.IsNullOrWhiteSpace(_esp8266TextBox.Text))
            {
                _esp8266TextBox.Text = _serialService.GenerateBoardUid("ESP8266");
            }
            if (_detectedBoard.Chip == "ESP32" && string.IsNullOrWhiteSpace(_esp32TextBox.Text))
            {
                _esp32TextBox.Text = _serialService.GenerateBoardUid("ESP32");
            }
            return;
        }

        if (string.IsNullOrWhiteSpace(_esp8266TextBox.Text))
        {
            _esp8266TextBox.Text = _serialService.GenerateBoardUid("ESP8266");
        }
        if (string.IsNullOrWhiteSpace(_esp32TextBox.Text))
        {
            _esp32TextBox.Text = _serialService.GenerateBoardUid("ESP32");
        }
    }

    private async Task AddHouseAsync()
    {
        await RunUiTaskAsync("Сохраняем объект...", async () =>
        {
            await _apiClient.CreateHouseAsync(_houseNameTextBox.Text, _houseAddressTextBox.Text);
            _houseNameTextBox.Clear();
            _houseAddressTextBox.Clear();
            ApplyObjects(await _apiClient.ListObjectsAsync());
        });
    }

    private async Task AddDoorAsync()
    {
        if (_houseCombo.SelectedItem is null || !_houseMap.TryGetValue(_houseCombo.SelectedItem.ToString() ?? string.Empty, out var houseId))
        {
            MessageBox.Show(this, "Сначала выберите объект.", "Дверь", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }

        await RunUiTaskAsync("Сохраняем дверь...", async () =>
        {
            await _apiClient.CreateDoorAsync(houseId, _doorNameTextBox.Text, _lockLabelTextBox.Text, _travelLineUnitTextBox.Text);
            _doorNameTextBox.Clear();
            _lockLabelTextBox.Clear();
            _travelLineUnitTextBox.Clear();
            ApplyObjects(await _apiClient.ListObjectsAsync());
        });
    }

    private async Task ActivateLockAsync()
    {
        ResetActivationProgress();

        if (_detectedBoard is null)
        {
            MessageBox.Show(this, "Сначала нажмите «Определить плату».", "Активация", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }

        GenerateIds(detectedOnly: true);
        var chip = _detectedBoard.Chip ?? string.Empty;
        var boardUid = chip == "ESP32" ? _esp32TextBox.Text.Trim() : _esp8266TextBox.Text.Trim();
        var lockId = _lockIdTextBox.Text.Trim();
        var wifiSsid = _wifiCombo.Text.Trim();
        var wifiPassword = _wifiPasswordTextBox.Text;
        var deviceName = string.IsNullOrWhiteSpace(_deviceNameTextBox.Text) ? lockId : _deviceNameTextBox.Text.Trim();
        var selectedDoorLabel = _doorCombo.SelectedItem?.ToString() ?? string.Empty;
        var doorId = _doorMap.TryGetValue(selectedDoorLabel, out var doorRef) ? doorRef.Id : null;
        var doorUid = _doorMap.TryGetValue(selectedDoorLabel, out var doorUidRef) ? doorUidRef.DoorUid : string.Empty;

        if (string.IsNullOrWhiteSpace(lockId) || string.IsNullOrWhiteSpace(boardUid) || string.IsNullOrWhiteSpace(wifiSsid) || string.IsNullOrWhiteSpace(wifiPassword))
        {
            MessageBox.Show(this, "Проверьте Lock ID, UID платы и настройки Wi-Fi.", "Активация", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }

        await RunUiTaskAsync("Активируем замок...", async () =>
        {
            UpdateActivationProgress(10, $"Проверяем плату на {_detectedBoard.Port} перед активацией...");
            _detectedBoard = await Task.Run(() => _serialService.IdentifyBoard(_detectedBoard.Port, timeout: TimeSpan.FromSeconds(8)));
            _boardInfoLabel.Text = $"{_detectedBoard.Chip} на {_detectedBoard.Port}, firmware: {_detectedBoard.FirmwareVersion ?? "не указана"}";

            UpdateActivationProgress(20, "Сохраняем замок через SmartLocker API...");
            var saveResult = await _apiClient.SaveLockAsync(
                lockId,
                deviceName,
                wifiSsid,
                wifiPassword,
                _portCombo.SelectedItem?.ToString() ?? string.Empty,
                doorId,
                _esp8266TextBox.Text.Trim(),
                _esp32TextBox.Text.Trim());

            var effectiveApiBaseUrl = string.IsNullOrWhiteSpace(_settings.ProvisioningApiBaseUrl)
                ? saveResult.Provisioning.ApiBaseUrl
                : _settings.ProvisioningApiBaseUrl;
            effectiveApiBaseUrl = effectiveApiBaseUrl.TrimEnd('/');
            saveResult.Provisioning.ApiBaseUrl = effectiveApiBaseUrl;

            UpdateActivationProgress(65, $"Записываем provisioning в {chip}...");
            await Task.Run(() => _serialService.ProvisionBoard(
                _detectedBoard.Port,
                chip,
                lockId,
                boardUid,
                deviceName,
                wifiSsid,
                wifiPassword,
                _user.Email,
                doorUid,
                saveResult.Provisioning.ApiKey,
                effectiveApiBaseUrl));

            _lastProvisioning = new ProvisioningView
            {
                LockId = saveResult.Provisioning.LockId,
                ApiKey = saveResult.Provisioning.ApiKey,
                ApiBaseUrl = effectiveApiBaseUrl,
            };
            ApplyLocks(await _apiClient.ListLocksAsync());
            FillLastProvisioning();
            UpdateActivationProgress(100, "Активация завершена.");

            MessageBox.Show(
                this,
                $"Конфигурация записана в {chip}.\n\nLock ID: {saveResult.Provisioning.LockId}\nAPI key: {saveResult.Provisioning.ApiKey}\nAPI URL: {saveResult.Provisioning.ApiBaseUrl}",
                "Активация",
                MessageBoxButtons.OK,
                MessageBoxIcon.Information);
        });
    }

    private async Task CheckHealthAsync()
    {
        await RunUiTaskAsync("Проверяем /health...", async () =>
        {
            var result = await _apiClient.HealthAsync();
            _lockTestResultLabel.Text = $"/health OK\nstatus: {result.Status}\nenvironment: {result.Environment}";
        });
    }

    private async Task FetchCurrentQrAsync()
    {
        await RunUiTaskAsync("Запрашиваем QR...", async () =>
        {
            var result = await _apiClient.GetCurrentQrAsync(_testLockIdTextBox.Text.Trim(), _testApiKeyTextBox.Text.Trim());
            _lockTestResultLabel.Text =
                $"QR получен.\n" +
                $"door_uid: {result.DoorUid}\n" +
                $"code: {result.Code}\n" +
                $"issued_at: {result.IssuedAt}\n" +
                $"expires_at: {result.ExpiresAt}\n" +
                $"ttl_seconds: {result.TtlSeconds}";
        });
    }

    private void ApplyPorts(IReadOnlyCollection<SerialBoardInfo> ports)
    {
        _portCombo.Items.Clear();
        foreach (var port in ports)
        {
            _portCombo.Items.Add(port.Port);
        }

        if (_portCombo.Items.Count > 0)
        {
            _portCombo.SelectedIndex = 0;
        }
    }

    private void ApplyWifiNetworks(IReadOnlyCollection<string> networks)
    {
        _wifiCombo.Items.Clear();
        foreach (var network in networks)
        {
            _wifiCombo.Items.Add(network);
        }

        if (_wifiCombo.Items.Count > 0)
        {
            _wifiCombo.SelectedIndex = 0;
        }
    }

    private void ApplyObjects(IReadOnlyCollection<HouseView> houses)
    {
        _houseMap.Clear();
        _doorMap.Clear();
        _houseCombo.Items.Clear();
        _doorCombo.Items.Clear();
        _doorCombo.Items.Add("Без привязки к двери");
        _doorCombo.SelectedIndex = 0;
        _objectsGrid.Rows.Clear();

        foreach (var house in houses)
        {
            var houseLabel = $"{house.Name} ({house.Address})";
            _houseMap[houseLabel] = house.Id;
            _houseCombo.Items.Add(houseLabel);

            if (house.Doors.Count == 0)
            {
                _objectsGrid.Rows.Add(house.Name, house.Address, "Нет дверей", string.Empty, string.Empty);
                continue;
            }

            foreach (var door in house.Doors)
            {
                var doorLabel = $"{house.Name} / {door.Name} ({door.DoorUid})";
                _doorMap[doorLabel] = new DoorBindingRef
                {
                    Id = door.Id,
                    DoorUid = door.DoorUid,
                    Label = doorLabel,
                };
                _doorCombo.Items.Add(doorLabel);
                _objectsGrid.Rows.Add(house.Name, house.Address, door.Name, door.DoorUid, door.LockLabel);
            }
        }

        if (_houseCombo.Items.Count > 0)
        {
            _houseCombo.SelectedIndex = 0;
        }
    }

    private void ApplyLocks(IReadOnlyCollection<LockDeviceView> devices)
    {
        _locksGrid.Rows.Clear();
        foreach (var device in devices)
        {
            var boards = new List<string>();
            if (!string.IsNullOrWhiteSpace(device.Esp8266Uid))
            {
                boards.Add($"ESP8266: {device.Esp8266Uid}");
            }
            if (!string.IsNullOrWhiteSpace(device.Esp32Uid))
            {
                boards.Add($"ESP32: {device.Esp32Uid}");
            }

            var door = string.IsNullOrWhiteSpace(device.DoorName)
                ? "Не привязан"
                : $"{device.HouseName} / {device.DoorName}";

            _locksGrid.Rows.Add(
                device.DeviceName,
                device.LockId,
                string.Join(", ", boards),
                device.WifiSsid,
                door,
                device.PortName,
                device.UpdatedAt);
        }
    }

    private void FillLastProvisioning()
    {
        if (_lastProvisioning is null)
        {
            return;
        }

        _testLockIdTextBox.Text = _lastProvisioning.LockId;
        _testApiKeyTextBox.Text = _lastProvisioning.ApiKey;
        _lockTestResultLabel.Text = "Подставлены данные последней активации.";
    }

    private void ResetActivationProgress()
    {
        _activationProgress.Value = 0;
        _activationLog.Clear();
    }

    private void UpdateActivationProgress(int percent, string message)
    {
        _activationProgress.Value = Math.Max(0, Math.Min(100, percent));
        if (!string.IsNullOrWhiteSpace(message))
        {
            _activationLog.AppendText(message + Environment.NewLine);
        }
    }

    private async Task RunUiTaskAsync(string statusText, Func<Task> action)
    {
        try
        {
            SetBusy(true, statusText);
            await action();
            SetBusy(false, "Готово.");
        }
        catch (Exception exc)
        {
            SetBusy(false, exc.Message);
            MessageBox.Show(this, exc.Message, "SmartLocker Desktop", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private void SetBusy(bool busy, string statusText)
    {
        UseWaitCursor = busy;
        _statusLabel.Text = statusText;
    }

    private void InstallDrivers()
    {
        if (!File.Exists(_settings.DriversScriptPath))
        {
            MessageBox.Show(this, $"Скрипт не найден: {_settings.DriversScriptPath}", "Драйверы", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }

        Process.Start(new ProcessStartInfo
        {
            FileName = "powershell",
            Arguments = $"-ExecutionPolicy Bypass -File \"{_settings.DriversScriptPath}\"",
            UseShellExecute = true,
        });
    }

    private static void OpenLocationSettings()
    {
        Process.Start(new ProcessStartInfo
        {
            FileName = "ms-settings:privacy-location",
            UseShellExecute = true,
        });
    }

    private void Logout()
    {
        DialogResult = DialogResult.Retry;
        Close();
    }
}
