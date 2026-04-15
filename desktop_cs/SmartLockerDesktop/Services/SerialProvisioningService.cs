using System.Diagnostics;
using System.IO.Ports;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using SmartLockerDesktop.Models;

namespace SmartLockerDesktop.Services;

public sealed class SerialProvisioningService
{
    private const string ProtocolName = "smartlocker-provisioning-v1";
    private const double PrepareDelaySeconds = 1.25;
    private const double InterAttemptDelaySeconds = 0.6;
    private static readonly TimeSpan StartupReadyTimeout = TimeSpan.FromSeconds(20);

    public List<SerialBoardInfo> ListPorts()
    {
        return SerialPort.GetPortNames()
            .OrderBy(static item => item, StringComparer.OrdinalIgnoreCase)
            .Select(port => new SerialBoardInfo
            {
                Port = port,
                Description = port,
            })
            .ToList();
    }

    public List<string> ListWifiNetworks()
    {
        try
        {
            using var process = new Process
            {
                StartInfo = new ProcessStartInfo
                {
                    FileName = "netsh",
                    Arguments = "wlan show networks mode=bssid",
                    RedirectStandardOutput = true,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                }
            };
            process.Start();
            var stdout = process.StandardOutput.ReadToEnd();
            if (!process.WaitForExit(10000) || process.ExitCode != 0)
            {
                return [];
            }

            var result = new List<string>();
            foreach (var rawLine in stdout.Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries))
            {
                var line = rawLine.Trim();
                if (!line.StartsWith("SSID ", StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                var separator = line.IndexOf(':');
                if (separator < 0 || separator + 1 >= line.Length)
                {
                    continue;
                }

                var ssid = line[(separator + 1)..].Trim();
                if (!string.IsNullOrWhiteSpace(ssid) && !result.Contains(ssid, StringComparer.Ordinal))
                {
                    result.Add(ssid);
                }
            }

            return result;
        }
        catch
        {
            return [];
        }
    }

    public SerialBoardInfo IdentifyBoard(string portName, int baudRate = 9600, TimeSpan? timeout = null)
    {
        var effectiveTimeout = timeout ?? TimeSpan.FromSeconds(5);
        var payload = JsonSerializer.Serialize(new { action = "identify", protocol = ProtocolName }) + "\n";
        var response = WithConnection(portName, baudRate, effectiveTimeout, connection => Request(connection, payload, effectiveTimeout, 4));

        var chip = ReadString(response, "chip").ToUpperInvariant();
        if (!IsSupportedChip(chip))
        {
            throw new InvalidOperationException("Плата не ответила корректным типом chip.");
        }

        return new SerialBoardInfo
        {
            Port = portName,
            Description = portName,
            Chip = chip,
            FirmwareVersion = ReadOptionalString(response, "firmware_version"),
            BoardUid = ReadOptionalString(response, "board_uid"),
            Protocol = ReadOptionalString(response, "protocol"),
        };
    }

    public Dictionary<string, object?> ProvisionBoard(
        string portName,
        string chip,
        string lockId,
        string boardUid,
        string deviceName,
        string wifiSsid,
        string wifiPassword,
        string ownerEmail,
        string doorUid,
        string apiKey,
        string apiBaseUrl,
        int baudRate = 9600,
        TimeSpan? timeout = null)
    {
        var effectiveTimeout = timeout ?? TimeSpan.FromSeconds(8);
        var identifyPayload = JsonSerializer.Serialize(new { action = "identify", protocol = ProtocolName }) + "\n";
        var payload = JsonSerializer.Serialize(new
        {
            action = "provision",
            protocol = ProtocolName,
            payload = new
            {
                chip = chip.Trim().ToUpperInvariant(),
                lock_id = lockId,
                board_uid = boardUid,
                device_name = deviceName,
                wifi_ssid = wifiSsid,
                wifi_password = wifiPassword,
                owner_email = ownerEmail,
                door_uid = doorUid,
                api_key = apiKey,
                api_base_url = apiBaseUrl,
            }
        }) + "\n";

        return WithConnection(portName, baudRate, effectiveTimeout, connection =>
        {
            WaitUntilReady(connection, identifyPayload, StartupReadyTimeout);
            try
            {
                return Request(connection, payload, effectiveTimeout, 4);
            }
            catch (TimeoutException)
            {
                if (TryConfirmProvisionedState(connection, chip, lockId, doorUid, StartupReadyTimeout, out var confirmedState))
                {
                    return confirmedState;
                }

                throw;
            }
        });
    }

    public string GenerateLockId() => $"LOCK-{RandomNumberGenerator.GetHexString(4)}";

    public string GenerateBoardUid(string chip)
    {
        var prefix = chip.Trim().ToUpperInvariant() switch
        {
            "ESP32-CAM" => "ESP32CAM",
            "ESP32" => "ESP32",
            _ => "ESP8266",
        };
        return $"{prefix}-{RandomNumberGenerator.GetHexString(4)}";
    }

    private static bool IsSupportedChip(string chip)
    {
        return chip is "ESP8266" or "ESP32" or "ESP32-CAM";
    }

    private static bool IsEsp32Family(string chip)
    {
        return chip is "ESP32" or "ESP32-CAM";
    }

    private static bool ChipsMatch(string expectedChip, string actualChip)
    {
        var normalizedExpected = expectedChip.Trim().ToUpperInvariant();
        var normalizedActual = actualChip.Trim().ToUpperInvariant();
        if (normalizedExpected == normalizedActual)
        {
            return true;
        }

        return IsEsp32Family(normalizedExpected) && IsEsp32Family(normalizedActual);
    }

    private static T WithConnection<T>(string portName, int baudRate, TimeSpan timeout, Func<SerialPort, T> action)
    {
        using var connection = new SerialPort(portName, baudRate)
        {
            ReadTimeout = 250,
            WriteTimeout = (int)Math.Max(timeout.TotalMilliseconds, 1000),
            Encoding = Encoding.UTF8,
            NewLine = "\n",
            Handshake = Handshake.None,
            DtrEnable = false,
            RtsEnable = false,
        };

        connection.Open();
        connection.DiscardInBuffer();
        connection.DiscardOutBuffer();
        Thread.Sleep(TimeSpan.FromSeconds(PrepareDelaySeconds));
        DrainIncomingNoise(connection);
        return action(connection);
    }

    private static Dictionary<string, object?> Request(SerialPort connection, string payload, TimeSpan timeout, int attempts)
    {
        for (var attempt = 0; attempt < attempts; attempt++)
        {
            connection.DiscardInBuffer();
            connection.Write(payload);
            connection.BaseStream.Flush();

            var deadline = DateTime.UtcNow + timeout;
            while (DateTime.UtcNow < deadline)
            {
                try
                {
                    var line = connection.ReadLine();
                    if (string.IsNullOrWhiteSpace(line))
                    {
                        continue;
                    }

                    var trimmed = line.Trim();
                    if (trimmed.StartsWith("STATUS:", StringComparison.OrdinalIgnoreCase))
                    {
                        continue;
                    }

                    using var doc = JsonDocument.Parse(trimmed);
                    if (doc.RootElement.TryGetProperty("ok", out var okElement)
                        && okElement.ValueKind == JsonValueKind.False)
                    {
                        throw new InvalidOperationException(ReadOptionalString(doc.RootElement, "error") ?? "Плата вернула ошибку provisioning.");
                    }

                    return ToDictionary(doc.RootElement);
                }
                catch (TimeoutException)
                {
                }
                catch (JsonException)
                {
                }
            }

            Thread.Sleep(TimeSpan.FromSeconds(InterAttemptDelaySeconds));
        }

        throw new TimeoutException("Плата не ответила по протоколу SmartLocker provisioning.");
    }

    private static void WaitUntilReady(SerialPort connection, string identifyPayload, TimeSpan timeout)
    {
        var deadline = DateTime.UtcNow + timeout;
        Exception? lastError = null;

        while (DateTime.UtcNow < deadline)
        {
            try
            {
                var response = Request(connection, identifyPayload, TimeSpan.FromSeconds(4), 1);
                var chip = ReadString(response, "chip").ToUpperInvariant();
                if (IsSupportedChip(chip))
                {
                    return;
                }
            }
            catch (Exception exc)
            {
                lastError = exc;
            }

            Thread.Sleep(TimeSpan.FromSeconds(InterAttemptDelaySeconds));
        }

        if (lastError is not null)
        {
            throw new TimeoutException("Плата не успела перезапуститься после прошивки и не ответила на identify.", lastError);
        }

        throw new TimeoutException("Плата не успела перезапуститься после прошивки и не ответила на identify.");
    }

    private static void DrainIncomingNoise(SerialPort connection)
    {
        var idleDeadline = DateTime.UtcNow + TimeSpan.FromMilliseconds(250);
        while (DateTime.UtcNow < idleDeadline)
        {
            try
            {
                if (connection.BytesToRead <= 0)
                {
                    Thread.Sleep(25);
                    continue;
                }

                connection.ReadExisting();
                idleDeadline = DateTime.UtcNow + TimeSpan.FromMilliseconds(250);
            }
            catch
            {
                break;
            }
        }

        try
        {
            connection.DiscardInBuffer();
        }
        catch
        {
        }
    }

    private static bool TryConfirmProvisionedState(
        SerialPort connection,
        string expectedChip,
        string expectedLockId,
        string expectedDoorUid,
        TimeSpan timeout,
        out Dictionary<string, object?> confirmedState)
    {
        var deadline = DateTime.UtcNow + timeout;

        while (DateTime.UtcNow < deadline)
        {
            try
            {
                var status = RequestJsonCommand(connection, "status-json\n", TimeSpan.FromSeconds(3), 1);
                var statusLockId = ReadString(status, "lock_id");
                var statusDoorUid = ReadString(status, "door_uid");
                if (string.Equals(statusLockId, expectedLockId, StringComparison.OrdinalIgnoreCase)
                    && (string.IsNullOrWhiteSpace(expectedDoorUid)
                        || string.Equals(statusDoorUid, expectedDoorUid, StringComparison.OrdinalIgnoreCase)))
                {
                    status["ok"] = true;
                    status["status"] = "provisioned";
                    confirmedState = status;
                    return true;
                }
            }
            catch
            {
            }

            try
            {
                var identifyPayload = JsonSerializer.Serialize(new { action = "identify", protocol = ProtocolName }) + "\n";
                var identify = Request(connection, identifyPayload, TimeSpan.FromSeconds(3), 1);
                var chip = ReadString(identify, "chip").ToUpperInvariant();
                var lockId = ReadString(identify, "lock_id");
                if (ChipsMatch(expectedChip, chip)
                    && string.Equals(lockId, expectedLockId, StringComparison.OrdinalIgnoreCase))
                {
                    identify["ok"] = true;
                    identify["status"] = "provisioned";
                    confirmedState = identify;
                    return true;
                }
            }
            catch
            {
            }

            Thread.Sleep(TimeSpan.FromSeconds(InterAttemptDelaySeconds));
        }

        confirmedState = new Dictionary<string, object?>(StringComparer.OrdinalIgnoreCase);
        return false;
    }

    private static Dictionary<string, object?> RequestJsonCommand(SerialPort connection, string command, TimeSpan timeout, int attempts)
    {
        for (var attempt = 0; attempt < attempts; attempt++)
        {
            connection.DiscardInBuffer();
            connection.Write(command);
            connection.BaseStream.Flush();

            var deadline = DateTime.UtcNow + timeout;
            while (DateTime.UtcNow < deadline)
            {
                try
                {
                    var line = connection.ReadLine();
                    if (string.IsNullOrWhiteSpace(line))
                    {
                        continue;
                    }

                    var trimmed = line.Trim();
                    if (!trimmed.StartsWith("{", StringComparison.Ordinal))
                    {
                        continue;
                    }

                    using var doc = JsonDocument.Parse(trimmed);
                    if (doc.RootElement.TryGetProperty("ok", out var okElement)
                        && okElement.ValueKind == JsonValueKind.False)
                    {
                        throw new InvalidOperationException(ReadOptionalString(doc.RootElement, "error") ?? "Плата вернула ошибку.");
                    }

                    return ToDictionary(doc.RootElement);
                }
                catch (TimeoutException)
                {
                }
                catch (JsonException)
                {
                }
            }

            Thread.Sleep(TimeSpan.FromSeconds(InterAttemptDelaySeconds));
        }

        throw new TimeoutException("Плата не вернула JSON-ответ на служебную команду.");
    }

    private static Dictionary<string, object?> ToDictionary(JsonElement element)
    {
        var result = new Dictionary<string, object?>(StringComparer.OrdinalIgnoreCase);
        foreach (var property in element.EnumerateObject())
        {
            result[property.Name] = property.Value.ValueKind switch
            {
                JsonValueKind.String => property.Value.GetString(),
                JsonValueKind.True => true,
                JsonValueKind.False => false,
                JsonValueKind.Number when property.Value.TryGetInt64(out var intValue) => intValue,
                JsonValueKind.Number when property.Value.TryGetDouble(out var doubleValue) => doubleValue,
                _ => property.Value.ToString(),
            };
        }

        return result;
    }

    private static string ReadString(IReadOnlyDictionary<string, object?> values, string key)
        => values.TryGetValue(key, out var value) ? Convert.ToString(value) ?? string.Empty : string.Empty;

    private static string? ReadOptionalString(IReadOnlyDictionary<string, object?> values, string key)
    {
        var value = ReadString(values, key);
        return string.IsNullOrWhiteSpace(value) ? null : value;
    }

    private static string? ReadOptionalString(JsonElement element, string key)
    {
        return element.TryGetProperty(key, out var property) && property.ValueKind == JsonValueKind.String
            ? property.GetString()
            : null;
    }
}
