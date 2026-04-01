using SmartLockerDesktop.Config;
using SmartLockerDesktop.Forms;

namespace SmartLockerDesktop;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);

        var settings = AppSettings.Load(
            AppContext.BaseDirectory,
            Directory.GetCurrentDirectory());

        Application.Run(new LoginForm(settings));
    }
}
