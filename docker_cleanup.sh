#!/usr/bin/env bash
# docker_cleanup.sh — Clean up Docker artefacts on EC2 between experiment runs
# Removes stopped containers, dangling images, and build cache to prevent
# disk space accumulation during repeated experiment runs.

# Usage
#   bash docker_cleanup.sh              # Normal cleanup
#   bash docker_cleanup.sh --full       # Full cleanup (removes ALL images)


set -euo pipefail

FULL_CLEAN="${1:-}"

echo "═══════════════════════════════════════════════════"
echo "  Docker Cleanup"
echo "═══════════════════════════════════════════════════"


echo ""
echo "BEFORE cleanup:"
sudo docker system df 2>/dev/null || true
echo ""
df -h / | tail -1 | awk '{print "  Disk: " $3 " used / " $2 " total (" $5 " used)"}'
echo ""

echo "Stopping all containers..."
sudo docker stop $(sudo docker ps -aq) 2>/dev/null || true
sudo docker rm $(sudo docker ps -aq) 2>/dev/null || true

echo "Removing dangling images..."
sudo docker image prune -f 2>/dev/null || true

# Remove build cache
echo "Removing build cache..."
sudo docker builder prune -f 2>/dev/null || true

if [ "$FULL_CLEAN" = "--full" ]; then
    echo "FULL CLEAN: Removing ALL images..."
    sudo docker rmi $(sudo docker images -aq) 2>/dev/null || true
    sudo docker system prune -af 2>/dev/null || true
fi

# Show result
echo ""
echo "AFTER cleanup:"
sudo docker system df 2>/dev/null || true
echo ""
df -h / | tail -1 | awk '{print "  Disk: " $3 " used / " $2 " total (" $5 " used)"}'
echo ""
echo "✓ Cleanup complete"
