using System.Text.Json.Serialization;

namespace SmartLockerDesktop.Models;

public sealed class LoginResponse
{
    [JsonPropertyName("access_token")]
    public string AccessToken { get; set; } = string.Empty;

    [JsonPropertyName("user")]
    public ApiUser User { get; set; } = new();
}

public sealed class ApiUser
{
    [JsonPropertyName("email")]
    public string Email { get; set; } = string.Empty;

    [JsonPropertyName("full_name")]
    public string FullName { get; set; } = string.Empty;

    [JsonPropertyName("role")]
    public string Role { get; set; } = "user";

    [JsonPropertyName("is_verified")]
    public bool IsVerified { get; set; }
}

public sealed class HousesEnvelope
{
    [JsonPropertyName("houses")]
    public List<HouseView> Houses { get; set; } = [];
}

public sealed class HouseEnvelope
{
    [JsonPropertyName("house")]
    public HouseView House { get; set; } = new();
}

public sealed class DoorEnvelope
{
    [JsonPropertyName("door")]
    public DoorView Door { get; set; } = new();
}

public sealed class LocksEnvelope
{
    [JsonPropertyName("devices")]
    public List<LockDeviceView> Devices { get; set; } = [];
}

public sealed class SaveLockEnvelope
{
    [JsonPropertyName("device")]
    public LockDeviceView Device { get; set; } = new();

    [JsonPropertyName("provisioning")]
    public ProvisioningView Provisioning { get; set; } = new();
}

public sealed class HealthResponse
{
    [JsonPropertyName("status")]
    public string Status { get; set; } = string.Empty;

    [JsonPropertyName("environment")]
    public string Environment { get; set; } = string.Empty;
}

public sealed class CurrentQrResponse
{
    [JsonPropertyName("door_uid")]
    public string DoorUid { get; set; } = string.Empty;

    [JsonPropertyName("code")]
    public string Code { get; set; } = string.Empty;

    [JsonPropertyName("issued_at")]
    public string IssuedAt { get; set; } = string.Empty;

    [JsonPropertyName("expires_at")]
    public string ExpiresAt { get; set; } = string.Empty;

    [JsonPropertyName("ttl_seconds")]
    public int TtlSeconds { get; set; }
}

public sealed class HouseView
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    [JsonPropertyName("name")]
    public string Name { get; set; } = string.Empty;

    [JsonPropertyName("address")]
    public string Address { get; set; } = string.Empty;

    [JsonPropertyName("doors")]
    public List<DoorView> Doors { get; set; } = [];
}

public sealed class DoorView
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    [JsonPropertyName("door_uid")]
    public string DoorUid { get; set; } = string.Empty;

    [JsonPropertyName("name")]
    public string Name { get; set; } = string.Empty;

    [JsonPropertyName("lock_label")]
    public string LockLabel { get; set; } = string.Empty;

    [JsonPropertyName("travelline_unit_id")]
    public string? TravelLineUnitId { get; set; }
}

public sealed class LockDeviceView
{
    [JsonPropertyName("lock_id")]
    public string LockId { get; set; } = string.Empty;

    [JsonPropertyName("device_name")]
    public string DeviceName { get; set; } = string.Empty;

    [JsonPropertyName("esp8266_uid")]
    public string? Esp8266Uid { get; set; }

    [JsonPropertyName("esp32_uid")]
    public string? Esp32Uid { get; set; }

    [JsonPropertyName("wifi_ssid")]
    public string WifiSsid { get; set; } = string.Empty;

    [JsonPropertyName("door_name")]
    public string? DoorName { get; set; }

    [JsonPropertyName("door_uid")]
    public string? DoorUid { get; set; }

    [JsonPropertyName("house_name")]
    public string? HouseName { get; set; }

    [JsonPropertyName("port_name")]
    public string PortName { get; set; } = string.Empty;

    [JsonPropertyName("updated_at")]
    public string UpdatedAt { get; set; } = string.Empty;
}

public sealed class ProvisioningView
{
    [JsonPropertyName("lock_id")]
    public string LockId { get; set; } = string.Empty;

    [JsonPropertyName("api_key")]
    public string ApiKey { get; set; } = string.Empty;

    [JsonPropertyName("api_base_url")]
    public string ApiBaseUrl { get; set; } = string.Empty;
}

public sealed class SerialBoardInfo
{
    public required string Port { get; init; }
    public required string Description { get; init; }
    public string Hwid { get; init; } = string.Empty;
    public string? Chip { get; init; }
    public string? FirmwareVersion { get; init; }
    public string? BoardUid { get; init; }
    public string? Protocol { get; init; }
}

public sealed class DoorBindingRef
{
    public required string Id { get; init; }
    public required string DoorUid { get; init; }
    public required string Label { get; init; }
}
