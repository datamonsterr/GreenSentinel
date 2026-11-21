#!/usr/bin/env bash
# Read-only evidence for startup delays, clock skew, and resource starvation.
set -u
echo "=== Runner UTC clock ==="
date -u '+%Y-%m-%dT%H:%M:%SZ'
echo "=== GitHub HTTP clock ==="
curl -sSI --connect-timeout 5 --max-time 10 https://api.github.com |
  sed -n '/^[Dd]ate:/p' || true
echo "=== CPU and load ==="
nproc
uptime
echo "=== Memory ==="
free -m
echo "=== Workspace disk ==="
df -h "${GITHUB_WORKSPACE:-.}"
echo "=== Cgroup limits and pressure ==="
for metric in cpu.max cpu.stat memory.max memory.events; do
  if [ -r "/sys/fs/cgroup/$metric" ]; then
    echo "$metric"
    cat "/sys/fs/cgroup/$metric"
  fi
done
for resource in cpu memory io; do
  if [ -r "/proc/pressure/$resource" ]; then
    echo "$resource pressure"
    cat "/proc/pressure/$resource"
  fi
done
