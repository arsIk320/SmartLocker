using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using SmartLockerDesktop.Models;

namespace SmartLockerDesktop.Services;

public sealed class SmartLockerApiClient : IDisposable
{
    private readonly HttpClient _httpClient;
    private readonly JsonSerializerOptions _jsonOptions = new() { PropertyNameCaseInsensitive = true };
    private string? _token;

    public SmartLockerApiClient(string baseUrl)
    {
        BaseUrl = baseUrl.TrimEnd('/');
        var handler = new SocketsHttpHandler
        {
            UseProxy = false,
            AllowAutoRedirect = true,
        };

        _httpClient = new HttpClient(handler)
        {
            BaseAddress = new Uri(BaseUrl),
            Timeout = TimeSpan.FromSeconds(20),
        };
    }

    public string BaseUrl { get; }

    public async Task<LoginResponse> LoginAsync(string email, string password, CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.PostAsJsonAsync(
            "/api/v1/client/auth/login",
            new { email, password },
            cancellationToken);

        var payload = await ReadPayloadAsync<LoginResponse>(response, cancellationToken);
        _token = payload.AccessToken;
        return payload;
    }

    public async Task<List<HouseView>> ListObjectsAsync(CancellationToken cancellationToken = default)
    {
        using var response = await SendAuthorizedAsync(HttpMethod.Get, "/api/v1/client/objects", cancellationToken);
        return (await ReadPayloadAsync<HousesEnvelope>(response, cancellationToken)).Houses;
    }

    public async Task<HouseView> CreateHouseAsync(string name, string address, CancellationToken cancellationToken = default)
    {
        using var request = CreateAuthorizedRequest(HttpMethod.Post, "/api/v1/client/objects/houses");
        request.Content = JsonContent.Create(new { name, address });
        using var response = await _httpClient.SendAsync(request, cancellationToken);
        return (await ReadPayloadAsync<HouseEnvelope>(response, cancellationToken)).House;
    }

    public async Task<DoorView> CreateDoorAsync(string houseId, string name, string lockLabel, string travelLineUnitId, CancellationToken cancellationToken = default)
    {
        using var request = CreateAuthorizedRequest(HttpMethod.Post, "/api/v1/client/objects/doors");
        request.Content = JsonContent.Create(new
        {
            house_id = houseId,
            name,
            lock_label = lockLabel,
            travelline_unit_id = string.IsNullOrWhiteSpace(travelLineUnitId) ? null : travelLineUnitId,
        });
        using var response = await _httpClient.SendAsync(request, cancellationToken);
        return (await ReadPayloadAsync<DoorEnvelope>(response, cancellationToken)).Door;
    }

    public async Task<List<LockDeviceView>> ListLocksAsync(CancellationToken cancellationToken = default)
    {
        using var response = await SendAuthorizedAsync(HttpMethod.Get, "/api/v1/client/locks", cancellationToken);
        return (await ReadPayloadAsync<LocksEnvelope>(response, cancellationToken)).Devices;
    }

    public async Task<SaveLockEnvelope> SaveLockAsync(
        string lockId,
        string deviceName,
        string wifiSsid,
        string wifiPassword,
        string portName,
        string? doorId,
        string esp8266Uid,
        string esp32Uid,
        CancellationToken cancellationToken = default)
    {
        using var request = CreateAuthorizedRequest(HttpMethod.Post, "/api/v1/client/locks");
        request.Content = JsonContent.Create(new
        {
            lock_id = lockId,
            device_name = deviceName,
            wifi_ssid = wifiSsid,
            wifi_password = wifiPassword,
            port_name = portName,
            door_id = doorId,
            esp8266_uid = esp8266Uid,
            esp32_uid = esp32Uid,
        });
        using var response = await _httpClient.SendAsync(request, cancellationToken);
        return await ReadPayloadAsync<SaveLockEnvelope>(response, cancellationToken);
    }

    public async Task<HealthResponse> HealthAsync(CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.GetAsync("/health", cancellationToken);
        return await ReadPayloadAsync<HealthResponse>(response, cancellationToken);
    }

    public async Task<CurrentQrResponse> GetCurrentQrAsync(string lockId, string apiKey, CancellationToken cancellationToken = default)
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, "/api/v1/locks/qr/current");
        request.Headers.Add("X-Lock-Id", lockId);
        request.Headers.Add("X-Lock-Api-Key", apiKey);
        using var response = await _httpClient.SendAsync(request, cancellationToken);
        return await ReadPayloadAsync<CurrentQrResponse>(response, cancellationToken);
    }

    private HttpRequestMessage CreateAuthorizedRequest(HttpMethod method, string url)
    {
        if (string.IsNullOrWhiteSpace(_token))
        {
            throw new InvalidOperationException("Сначала выполните вход в SmartLocker API.");
        }

        var request = new HttpRequestMessage(method, url);
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _token);
        return request;
    }

    private async Task<HttpResponseMessage> SendAuthorizedAsync(HttpMethod method, string url, CancellationToken cancellationToken)
    {
        using var request = CreateAuthorizedRequest(method, url);
        return await _httpClient.SendAsync(request, cancellationToken);
    }

    private async Task<T> ReadPayloadAsync<T>(HttpResponseMessage response, CancellationToken cancellationToken)
    {
        if (!response.IsSuccessStatusCode)
        {
            throw new InvalidOperationException(await ReadErrorAsync(response, cancellationToken));
        }

        await using var stream = await response.Content.ReadAsStreamAsync(cancellationToken);
        var payload = await JsonSerializer.DeserializeAsync<T>(stream, _jsonOptions, cancellationToken);
        if (payload is null)
        {
            throw new InvalidOperationException("SmartLocker API вернул пустой ответ.");
        }

        return payload;
    }

    private static async Task<string> ReadErrorAsync(HttpResponseMessage response, CancellationToken cancellationToken)
    {
        var content = await response.Content.ReadAsStringAsync(cancellationToken);
        if (string.IsNullOrWhiteSpace(content))
        {
            return $"HTTP {(int)response.StatusCode} {response.ReasonPhrase}";
        }

        try
        {
            using var doc = JsonDocument.Parse(content);
            if (doc.RootElement.TryGetProperty("detail", out var detail))
            {
                return detail.GetString() ?? content;
            }
        }
        catch
        {
        }

        return content;
    }

    public void Dispose()
    {
        _httpClient.Dispose();
    }
}
