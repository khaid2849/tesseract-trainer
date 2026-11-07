#!/usr/bin/env bash
# Chạy vod.sh dưới systemd: mất SSH hay tắt máy Mac không làm dừng. Tham số y như vod.sh.
#   ./vod-bg.sh download --source congbao_pairs
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
[ $# -ge 1 ] || { echo "Dùng: ./vod-bg.sh <lệnh của vod.sh> [tham số]   (vd. ./vod-bg.sh extract)" >&2; exit 2; }

if [ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != yes ]; then
  echo "== Bật linger cho $USER (cần sudo một lần) để việc chạy tiếp khi đóng SSH"
  sudo loginctl enable-linger "$USER"
fi

UNIT="vod-$1-$(date +%m%d-%H%M%S)"
ENV=(--setenv=PYTHONUNBUFFERED=1)
for var in VOD_HOME TT_PYTHON; do
  if [ -n "${!var:-}" ]; then ENV+=("--setenv=$var=${!var}"); fi
done
systemd-run --user --quiet --collect --unit "$UNIT" "${ENV[@]}" "$DIR/vod.sh" "$@"
cat <<EOF
Đã chạy nền: $UNIT
  Xem tiến độ:  journalctl --user -u $UNIT -f        (Ctrl+C chỉ thoát xem, việc vẫn chạy)
  Đang chạy gì: systemctl --user list-units 'vod-*'
  Dừng:         systemctl --user stop $UNIT
Chạy lại cùng lệnh khi bị dừng: phần đã xong được bỏ qua.
EOF
