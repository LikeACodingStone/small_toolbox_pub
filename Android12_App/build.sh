#!/usr/bin/env bash
# Build RingPlayer. Usage: ./build.sh [compile|debug]   (default: debug)
#   compile  - Java compile check only (fast)
#   debug    - assembleDebug + lintDebug, APK in app/build/outputs/apk/debug/
set -euo pipefail
cd "$(dirname "$0")"

export JAVA_HOME="${JAVA_HOME:-/usr/lib/jvm/java-17-openjdk-amd64}"
export ANDROID_HOME="${ANDROID_HOME:-$HOME/Android/Sdk}"

if [ ! -x "$JAVA_HOME/bin/java" ]; then
  echo "JDK 17 not found at $JAVA_HOME. Install it (sudo apt install openjdk-17-jdk) or set JAVA_HOME." >&2
  exit 1
fi
if [ ! -d "$ANDROID_HOME" ] && ! grep -q '^sdk.dir=' local.properties 2>/dev/null; then
  echo "Android SDK not found at $ANDROID_HOME. Set ANDROID_HOME or sdk.dir in local.properties." >&2
  exit 1
fi

case "${1:-debug}" in
  compile) ./gradlew compileDebugJavaWithJavac ;;
  debug)   ./gradlew assembleDebug lintDebug
           echo "APK: $(pwd)/app/build/outputs/apk/debug/app-debug.apk" ;;
  *) echo "Usage: $0 [compile|debug]" >&2; exit 2 ;;
esac
