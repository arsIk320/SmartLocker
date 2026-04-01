using SmartLockerDesktop.Config;
using SmartLockerDesktop.Services;

namespace SmartLockerDesktop.Forms;

public sealed class LoginForm : Form
{
    private readonly AppSettings _settings;
    private readonly SmartLockerApiClient _apiClient;
    private readonly TextBox _emailTextBox = new() { PlaceholderText = "Email", Width = 320 };
    private readonly TextBox _passwordTextBox = new() { PlaceholderText = "Пароль", Width = 320, UseSystemPasswordChar = true };
    private readonly Button _loginButton = new() { Text = "Войти", Width = 160, Height = 40 };
    private readonly Label _statusLabel = new() { AutoSize = true };

    public LoginForm(AppSettings settings)
    {
        _settings = settings;
        _apiClient = new SmartLockerApiClient(settings.ApiBaseUrl);

        Text = "SmartLocker Desktop";
        Width = 920;
        Height = 560;
        StartPosition = FormStartPosition.CenterScreen;

        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 2,
            Padding = new Padding(24),
        };
        root.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 55));
        root.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 45));

        root.Controls.Add(BuildHeroPanel(), 0, 0);
        root.Controls.Add(BuildLoginPanel(), 1, 0);
        Controls.Add(root);

        AcceptButton = _loginButton;
    }

    private Control BuildHeroPanel()
    {
        var panel = new Panel { Dock = DockStyle.Fill, Padding = new Padding(8) };
        var title = new Label
        {
            Text = "SmartLocker Desktop",
            Font = new Font("Segoe UI", 24, FontStyle.Bold),
            AutoSize = true,
        };
        var body = new Label
        {
            AutoSize = true,
            MaximumSize = new Size(440, 0),
            Text =
                "Новый Windows-клиент работает через SmartLocker API и одну общую серверную базу.\n\n" +
                "1. Войдите в аккаунт SmartLocker.\n" +
                "2. Подключите плату к компьютеру.\n" +
                "3. Определите плату и выберите Wi-Fi.\n" +
                "4. Сохраните замок через API и запишите provisioning в плату.\n" +
                "5. Проверьте /health и текущий QR прямо из клиента.",
        };

        var layout = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.TopDown,
            WrapContents = false,
            AutoScroll = true,
        };
        layout.Controls.Add(title);
        layout.Controls.Add(body);
        panel.Controls.Add(layout);
        return panel;
    }

    private Control BuildLoginPanel()
    {
        var panel = new Panel { Dock = DockStyle.Fill, Padding = new Padding(24) };
        var title = new Label
        {
            Text = "Вход в аккаунт",
            Font = new Font("Segoe UI", 18, FontStyle.Bold),
            AutoSize = true,
        };

        var hint = new Label
        {
            Text = $"API: {_settings.ApiBaseUrl}\nТестовый админ: {_settings.AdminEmail}\nПароль: {_settings.AdminPassword}",
            AutoSize = true,
            MaximumSize = new Size(360, 0),
        };

        _loginButton.Click += async (_, _) => await LoginAsync();

        var stack = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.TopDown,
            WrapContents = false,
            AutoScroll = true,
        };
        stack.Controls.Add(title);
        stack.Controls.Add(new Label { Text = "Используйте подтверждённый аккаунт SmartLocker.", AutoSize = true });
        stack.Controls.Add(_emailTextBox);
        stack.Controls.Add(_passwordTextBox);
        stack.Controls.Add(_loginButton);
        stack.Controls.Add(_statusLabel);
        stack.Controls.Add(hint);

        panel.Controls.Add(stack);
        return panel;
    }

    private async Task LoginAsync()
    {
        try
        {
            ToggleBusy(true, "Выполняем вход...");
            var login = await _apiClient.LoginAsync(_emailTextBox.Text.Trim(), _passwordTextBox.Text);

            using var main = new MainForm(_settings, _apiClient, login.User);
            Hide();
            var result = main.ShowDialog(this);
            if (result == DialogResult.Retry)
            {
                Show();
                ToggleBusy(false, "Сессия завершена.");
                return;
            }

            Close();
        }
        catch (Exception exc)
        {
            ToggleBusy(false, exc.Message);
            MessageBox.Show(this, exc.Message, "Ошибка входа", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private void ToggleBusy(bool busy, string status)
    {
        _loginButton.Enabled = !busy;
        _emailTextBox.Enabled = !busy;
        _passwordTextBox.Enabled = !busy;
        _statusLabel.Text = status;
        UseWaitCursor = busy;
    }
}
