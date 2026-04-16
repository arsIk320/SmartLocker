namespace SmartLockerDesktop.Config;

public sealed class AppSettings
{
    public required string ApiBaseUrl { get; init; }
    public required string ProvisioningApiBaseUrl { get; init; }
    public required string AdminEmail { get; init; }
    public required string AdminPassword { get; init; }
    public required string DriversScriptPath { get; init; }

    public static AppSettings Load(params string[] roots)
    {
        var values = EnvLoader.Load(roots);

        static string Read(IDictionary<string, string> values, string key, string fallback = "")
            => values.TryGetValue(key, out var value) ? value.Trim() : fallback;

        var apiBaseUrl = FirstNonBlank(
            Read(values, "SMARTLOCKER_API_BASE_URL"),
            Read(values, "PROVISIONING_API_BASE_URL"),
            "http://188.130.251.23");

        return new AppSettings
        {
            ApiBaseUrl = apiBaseUrl.TrimEnd('/'),
            ProvisioningApiBaseUrl = FirstNonBlank(
                Read(values, "PROVISIONING_API_BASE_URL"),
                apiBaseUrl).TrimEnd('/'),
            AdminEmail = FirstNonBlank(Read(values, "ADMIN_EMAIL"), "admin@smartlocker.local"),
            AdminPassword = FirstNonBlank(Read(values, "ADMIN_PASSWORD"), "Admin123!"),
            DriversScriptPath = Path.Combine(roots.LastOrDefault() ?? AppContext.BaseDirectory, "scripts", "install_bundled_drivers.ps1"),
        };
    }

    private static string FirstNonBlank(params string[] candidates)
        => candidates.FirstOrDefault(static item => !string.IsNullOrWhiteSpace(item)) ?? string.Empty;
}
