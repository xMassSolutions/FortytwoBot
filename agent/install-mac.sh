#!/usr/bin/env bash
# Install the FortytwoBot agent as a launchd service on macOS/Linux.
#
# Usage:
#   ./install-mac.sh <bot-url> <agent-token> <scripts-root> [docker-container]
#
# After install, the agent runs at user login, restarts on failure, and writes
# logs to ~/Library/Logs/fortytwo-agent.log (macOS) or ~/.cache/fortytwo-agent.log (Linux).
#
# Pass a docker-container name as the 4th arg if the FortyTwo node is running
# inside a Docker container (the agent will use `docker top` / `docker inspect`
# instead of pgrep). Leave blank for native installs.

set -euo pipefail

if [[ $# -lt 3 ]]; then
    cat <<EOF >&2
Usage: $0 <bot-url> <agent-token> <scripts-root> [docker-container]

Example (native):
    $0 https://fortytwo-network-node-analysis.onrender.com \\
        \$(openssl rand -hex 20) \\
        ~/FortytwoCLI/fortytwo-p2p-inference-scripts-main

Example (Docker — pass the container name as the 4th arg):
    $0 https://fortytwo-network-node-analysis.onrender.com \\
        \$(openssl rand -hex 20) \\
        ~/fortytwo-data/scripts \\
        fortytwo-p2p-inference
EOF
    exit 2
fi

BOT_URL="$1"
AGENT_TOKEN="$2"
SCRIPTS_ROOT="$3"
DOCKER_CONTAINER="${4:-}"

# Resolve script directory
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT="$HERE/push_agent.py"

if [[ ! -f "$AGENT" ]]; then
    echo "ERROR: push_agent.py not found at $AGENT" >&2
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 not on PATH. Install Python 3 first." >&2
    exit 1
fi

# Expand scripts-root if it starts with ~
SCRIPTS_ROOT="${SCRIPTS_ROOT/#\~/$HOME}"

if [[ ! -d "$SCRIPTS_ROOT" ]]; then
    echo "WARNING: $SCRIPTS_ROOT does not exist. Agent will fail until logs appear there." >&2
fi

chmod +x "$AGENT"

# Determine log path + LaunchAgents dir per OS
case "$(uname -s)" in
    Darwin)
        LAUNCH_DIR="$HOME/Library/LaunchAgents"
        LOG_PATH="$HOME/Library/Logs/fortytwo-agent.log"
        ;;
    Linux)
        LAUNCH_DIR="$HOME/.config/systemd/user"  # Linux uses systemd, not launchd
        LOG_PATH="$HOME/.cache/fortytwo-agent.log"
        echo "WARNING: Linux detected. This installer only configures macOS launchd." >&2
        echo "  Run the agent manually or write a systemd unit:" >&2
        echo "  python3 $AGENT --bot-url $BOT_URL --agent-token <hidden> --scripts-root $SCRIPTS_ROOT" >&2
        exit 1
        ;;
    *)
        echo "ERROR: unsupported OS $(uname -s). macOS only for now." >&2
        exit 1
        ;;
esac

mkdir -p "$LAUNCH_DIR"
mkdir -p "$(dirname "$LOG_PATH")"

PLIST="$LAUNCH_DIR/com.fortytwo.agent.plist"
TEMPLATE="$HERE/com.fortytwo.agent.plist"

# Compose optional --docker-container argument pair for the plist
if [[ -n "$DOCKER_CONTAINER" ]]; then
    EXTRA_ARGS="<string>--docker-container</string><string>$DOCKER_CONTAINER</string>"
else
    EXTRA_ARGS=""
fi

# Render template
sed \
    -e "s|{{AGENT_PATH}}|$AGENT|g" \
    -e "s|{{BOT_URL}}|$BOT_URL|g" \
    -e "s|{{AGENT_TOKEN}}|$AGENT_TOKEN|g" \
    -e "s|{{SCRIPTS_ROOT}}|$SCRIPTS_ROOT|g" \
    -e "s|{{EXTRA_ARGS}}|$EXTRA_ARGS|g" \
    -e "s|{{LOG_PATH}}|$LOG_PATH|g" \
    "$TEMPLATE" >"$PLIST"

# Reload
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo "Agent installed:"
echo "  Plist:       $PLIST"
echo "  Log:         $LOG_PATH"
echo "  Scripts:     $SCRIPTS_ROOT"
echo "  Bot URL:     $BOT_URL"
if [[ -n "$DOCKER_CONTAINER" ]]; then
    echo "  Docker:      $DOCKER_CONTAINER (using \`docker top\` for process detection)"
fi
echo
echo "Verify within ~30s:"
echo "  tail -f $LOG_PATH"
echo
echo "Uninstall:"
echo "  ./uninstall-mac.sh"
