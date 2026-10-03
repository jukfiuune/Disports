#!/bin/bash
# run.sh <name> <screenshot-ms> [VAR=value ...]
#
# Runs the app once, signed in to the fake server (tools/test/server.sh),
# in the test container (localhost/disports-test-gl), and saves a
# screenshot to build/test/<name>/shot.png when it quits after
# <screenshot-ms>. Output: build/test/<name>/log.txt; sanitizer reports
# (sanitizer builds) as build/test/<name>/asan.* / ubsan.*.
#
# STEPS drives it with xdotool, ";"-separated: "sleep 2;click 700 772;drag x1 y1 x2 y2;
# type hi @bo;key Return;wheel 30 400 5" (5 scroll steps down at 30,400; -5 up).
# APP_INSTALL picks the build to run (default: check.sh's, which has the
# test hooks). Files for tests go in
# build/test/files (/files in the container). Test hooks
# (DISPORTS_OPEN_CHANNEL, ...): src/testing/TestHooks.h.
HERE=$(dirname "$(readlink -f "$0")")
ROOT=$(readlink -f "$HERE/../..")
NAME=$1; DELAY=$2; shift 2
INSTALL=${APP_INSTALL:-$ROOT/build/asan/app/install}
OUT=$ROOT/build/test/$NAME
rm -rf "$OUT"; mkdir -p "$OUT/data/disports.jukfiuu" "$ROOT/build/test/files"
# LOGGED_OUT=1: no saved token, the app starts at the sign-in page.
[ -n "${LOGGED_OUT:-}" ] || echo '{"Token": "test-token"}' > "$OUT/data/disports.jukfiuu/settings.json"
# LEGACY=1: what Disports 0.8.5 (Qt 5) left, to be migrated (src/Migration.h):
# its token file and settings, and none of this version's. LEGACY_TOKEN: the
# token in it ("none": no token file, as if never signed in).
if [ -n "${LEGACY:-}" ]; then
    rm -f "$OUT/data/disports.jukfiuu/settings.json"
    [ "${LEGACY_TOKEN:-}" = none ] || printf '%s\n' "${LEGACY_TOKEN:-test-token}" > "$OUT/data/disports.jukfiuu/token"
    mkdir -p "$OUT/.config/disports.jukfiuu"
    printf '[General]\nblockedMessageVisibility=hide\ninlineGifPlayback=true\nmaxComposerLines=5\nthemeMode=1\ntoken=\nuitkTheme=Lomiri.Components.Themes.SuruDark\n' \
        > "$OUT/.config/disports.jukfiuu/disports.jukfiuu.conf"
fi
# AUTOPLAY=1: "Play GIFs automatically" on.
if [ -n "${AUTOPLAY:-}" ]; then
    mkdir -p "$OUT/.config/disports.jukfiuu"
    printf '[chat]\nautoplayGifs=true\n' >> "$OUT/.config/disports.jukfiuu/preferences.ini"
fi
# THEME=dark (or light): the app's theme setting.
if [ -n "${THEME:-}" ]; then
    mkdir -p "$OUT/.config/disports.jukfiuu"
    printf '[appearance]\ntheme=%s\n' "$([ "$THEME" = dark ] && echo 1 || echo 0)" > "$OUT/.config/disports.jukfiuu/preferences.ini"
fi
ENVS=(); for kv in "$@"; do ENVS+=(-e "$kv"); done
cat > "$OUT/inner.sh" <<'INNER'
Xvfb :99 -screen 0 1280x2000x24 -nolisten tcp >/dev/null 2>&1 &
sleep 1
export DISPLAY=:99
/app/bin/disports &
app=$!
IFS=';' read -ra steps <<< "$STEPS"
for step in "${steps[@]}"; do
    set -- $step
    win=$(xdotool search --name Disports | head -1)
    case $1 in
        sleep) sleep "$2" ;;
        click) xdotool mousemove --window "$win" "$2" "$3" click 1 ;;
        drag) xdotool mousemove --window "$win" "$2" "$3" mousedown 1
              for i in 1 2 3 4 5 6 7 8; do
                  xdotool mousemove --window "$win" $(( $2 + ($4 - $2) * i / 8 )) $(( $3 + ($5 - $3) * i / 8 )); sleep 0.03
              done
              xdotool mouseup 1 ;;
        wheel) if [ "$4" -lt 0 ]; then xdotool mousemove --window "$win" "$2" "$3" click --repeat "${4#-}" --delay 60 4
               else xdotool mousemove --window "$win" "$2" "$3" click --repeat "$4" --delay 60 5; fi ;;
        type) xdotool windowfocus --sync "$win" 2>/dev/null; shift; xdotool type --delay 80 "$*" ;;
        key) xdotool windowfocus --sync "$win" 2>/dev/null; xdotool key "$2" ;;
    esac
done
wait $app
echo "app exit: $?"
INNER
# --timeout: podman kills the container itself (a `timeout` in front of
# podman only stops the client, and the container would keep running).
podman run --rm --timeout 150 --network=host --cap-add SYS_PTRACE \
    -v "$INSTALL":/app:ro -v "$OUT":/out:Z -v "$HERE":/tools:ro,Z -v "$ROOT/build/test/files":/files:ro,Z \
    -e LANG=C.UTF-8 -e APP_DIR=/app -e QT_QPA_PLATFORM=xcb -e LIBGL_ALWAYS_SOFTWARE=1 \
    -e XDG_DATA_HOME=/out/data -e HOME=/out -e LD_LIBRARY_PATH=/app/lib/x86_64-linux-gnu \
    -e DISPORTS_SCREENSHOT=/out/shot.png:"$DELAY" \
    -e DISPORTS_API_URL=http://127.0.0.1:8811/api/v9/ -e DISPORTS_CDN_URL=http://127.0.0.1:8811/ \
    -e ASAN_OPTIONS="log_path=/out/asan:detect_leaks=1:abort_on_error=0" \
    -e LSAN_OPTIONS="exitcode=0" \
    -e UBSAN_OPTIONS="log_path=/out/ubsan:print_stacktrace=1" \
    -e STEPS="$STEPS" "${ENVS[@]}" -w /app localhost/disports-test-gl:latest bash /out/inner.sh \
    > "$OUT/log.txt" 2>&1
