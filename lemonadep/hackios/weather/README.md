# Weather's local-server shim (2026-11-03, experimental)

`inject_weather.c` builds `/redwood/lib/libredwood-weather.dylib`: a library that goes **inside** the Weather
processes and gives WeatherCore the environment Apple calls **"Local - Mock Server"** — a plain-HTTP data
endpoint at `http://localhost:5033`, with no Mescal signature and no TLS.

This is not part of the verified standalone image. It is the beginning of the Weather work described in
[`../FINDINGS-2026-11-01-03.md`](../FINDINGS-2026-11-01-03.md) §4, kept here so the next person does not have
to re-derive the keys.

## Why these keys

Read out of the dyld shared cache (`ios165/20F66__iPhone10,3_6/dyld_shared_cache_arm64.13`), where
WeatherCore's code actually lives — the framework on the volume has only plists. The keys sit together in one
string table, with the two environment display names beside them:

```
weather.environment.aps
weather.environment.contentEnvironment      "Production - Origin" / "Local - Mock Server"
weather.environment.localServerPort
weather.environment.localServerURL          next to the literal "http://localhost"
```

That is why the URL never appears as a whole `localhost:5033` string anywhere: host and port are two keys, and
the selector is a defaults value.

## What the library does

1. In a constructor — before the app's `main`, so before anything can read the keys — it writes
   `weather.environment.contentEnvironment` = `"Local - Mock Server"`,
   `weather.environment.localServerURL` = `"http://localhost"` and
   `weather.environment.localServerPort` = `5033`, in both `com.apple.weather` and the current application's
   domain.
2. It starts a thread listening on `127.0.0.1:5033`. Every request line and header is written to
   `/dev/console` (prefix `redwood: Weather:`), and the answer is `/var/mobile/redwood-weather.json` when that
   file exists, `{}` otherwise, always `200` with `application/json`. That is a deliberate probe: the paths the
   app builds are not in the cache, so the first boot has to report them.

## How to wire it (three edits in `userland/build.sh`)

```sh
# 1. after the libredwood-app line of the default INJECT list
/redwood/lib/libredwood-weather.dylib Weather WeatherWidget weatherd

# 2. beside the other $DYN dynamiclib rules
$DYN -dynamiclib -install_name /redwood/lib/libredwood-weather.dylib -framework CoreFoundation \
	-o obj/libredwood-weather.dylib src/inject_weather.c

# 3. beside the other copies into the image
[ -f obj/libredwood-weather.dylib ] && cp obj/libredwood-weather.dylib root/lib/
```

`etc/inject.conf` is what `kern.exec_inject` reads (one `LIBRARY NAME...` line per entry), so the daemon and
the widget extension are covered as well as the app — the process that fetches is not necessarily the one that
is on screen.

Note: build the image with `GL=1` exported yourself. `USERLAND_VARS=...` belongs to the upstream
`common/build.sh` wrapper; passing it to `userland/build.sh` silently produces an 18.6 MB image without Mesa.

## Result on the phone (run `weathershim3`, 250 s)

```
redwood: Weather: defaults weather.environment.contentEnvironment set
redwood: Weather: defaults weather.environment.localServerURL set
redwood: Weather: defaults weather.environment.localServerPort set
redwood: Weather: the local server listens on 127.0.0.1:5033, answering /var/mobile/redwood-weather.json
Successfully spawned Weather[41]
```

…and **zero requests**. No Mescal error either, unlike 1 November. The app reached the foreground
(`<sceneID:com.apple.weather-default> unspecified -> foreground`) and then did nothing.

## What to try next

1. Remove the `set_pref(... contentEnvironment ...)` line (or read the value from a file), rebuild, boot with
   the server still listening. If the Mescal `code=12` error returns, the Local selection works and only the
   URL shape is wrong; if it does not, the keys are read from another domain than the one written.
2. Add a watch on `-[NSUserDefaults objectForKey:]` that logs every `weather.*` read. That says whether the
   framework asks for these keys at all — the missing fact behind both readings.
3. Only then write the JSON: the request the app eventually makes names the paths and, through its decoder's
   complaints, the fields it needs. `OPEN-METEO`-shaped data is the keyless source to translate from.

## Getting the app to start without a finger

Nothing in this port can launch an application without a touch, so `src/inject_sb.c` gained an opt-in
opener: if `/var/mobile/redwood-open` exists, its single line is a bundle id and it is opened 25/45/65 s after
SpringBoard starts. It logs `refused` from `-[LSApplicationWorkspace openApplicationWithBundleID:]` while
FrontBoard spawns the app anyway, so do not trust that return value.
