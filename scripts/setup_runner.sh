#!/bin/bash
set -e

# Target directory
RUNNER_DIR="/home/nathan/runners/mealie-planner"
SOURCE_DIR="/home/nathan/runners/curbclass"

echo "=== GitHub self-hosted runner setup for mealie-planner ==="

if [ ! -d "$SOURCE_DIR" ]; then
    echo "Error: Source runner directory $SOURCE_DIR not found."
    exit 1
fi

echo "Creating runner directory: $RUNNER_DIR..."
mkdir -p "$RUNNER_DIR"

echo "Copying runner binary files from $SOURCE_DIR..."
cp -rp "$SOURCE_DIR/bin" "$RUNNER_DIR/"
cp -rp "$SOURCE_DIR/externals" "$RUNNER_DIR/"
cp -p "$SOURCE_DIR/config.sh" "$RUNNER_DIR/"
cp -p "$SOURCE_DIR/env.sh" "$RUNNER_DIR/"
cp -p "$SOURCE_DIR/run.sh" "$RUNNER_DIR/"
cp -p "$SOURCE_DIR/run-helper.sh" "$RUNNER_DIR/"
cp -p "$SOURCE_DIR/safe_sleep.sh" "$RUNNER_DIR/"
cp -p "$SOURCE_DIR/svc.sh" "$RUNNER_DIR/"

# Ensure correct permissions
chmod +x "$RUNNER_DIR"/*.sh

echo "Creating systemd user service file..."
SERVICE_DIR="/home/nathan/.config/systemd/user"
mkdir -p "$SERVICE_DIR"

cat << 'EOF' > "$SERVICE_DIR/github-runner-mealie-planner.service"
[Unit]
Description=GitHub Actions Runner - mealie-planner
After=network.target

[Service]
WorkingDirectory=/home/nathan/runners/mealie-planner
ExecStart=/home/nathan/runners/mealie-planner/run.sh
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
EOF

echo "Systemd service file created at: $SERVICE_DIR/github-runner-mealie-planner.service"
echo ""
echo "=== SETUP COMPLETE ==="
echo "To register and start your new runner, follow these steps:"
echo "1. Go to your GitHub repository settings: https://github.com/ncrosty58/mealie-planner/settings/actions/runners"
echo "2. Click 'New self-hosted runner' and copy the token from the config.sh command line."
echo "3. Run the configuration command:"
echo "   cd $RUNNER_DIR"
echo "   ./config.sh --url https://github.com/ncrosty58/mealie-planner --token <YOUR_TOKEN>"
echo "4. Reload systemd and start the service:"
echo "   systemctl --user daemon-reload"
echo "   systemctl --user enable --now github-runner-mealie-planner"
echo ""
echo "After starting, your runner will connect and you can push to deploy!"
