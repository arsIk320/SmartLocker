namespace SmartLockerDesktop.Config;

internal static class EnvLoader
{
    public static Dictionary<string, string> Load(params string[] roots)
    {
        var values = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        var fileNames = new[] { ".env.example", ".env", "SmartLocker.env", ".local.env" };

        foreach (var root in ExpandRoots(roots))
        {
            foreach (var fileName in fileNames)
            {
                var path = Path.Combine(root, fileName);
                if (!File.Exists(path))
                {
                    continue;
                }

                foreach (var rawLine in File.ReadAllLines(path))
                {
                    var line = rawLine.Trim();
                    if (string.IsNullOrWhiteSpace(line) || line.StartsWith('#'))
                    {
                        continue;
                    }

                    var separatorIndex = line.IndexOf('=');
                    if (separatorIndex <= 0)
                    {
                        continue;
                    }

                    var key = line[..separatorIndex].Trim();
                    var value = line[(separatorIndex + 1)..].Trim().Trim('"');
                    values[key] = value;
                }
            }
        }

        foreach (System.Collections.DictionaryEntry item in Environment.GetEnvironmentVariables())
        {
            if (item.Key is string key && item.Value is string value && !string.IsNullOrWhiteSpace(value))
            {
                values[key] = value;
            }
        }

        return values;
    }

    private static IEnumerable<string> ExpandRoots(IEnumerable<string> roots)
    {
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        foreach (var rawRoot in roots.Where(static path => !string.IsNullOrWhiteSpace(path)))
        {
            var current = new DirectoryInfo(rawRoot);
            var chain = new Stack<string>();

            while (current is not null)
            {
                chain.Push(current.FullName);
                current = current.Parent;
            }

            while (chain.Count > 0)
            {
                var path = chain.Pop();
                if (seen.Add(path))
                {
                    yield return path;
                }
            }
        }
    }
}
