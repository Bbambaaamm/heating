#!/bin/sh
set -eu

REGISTRY_FILE="/config/.storage/core.entity_registry"
OUT_DIR="/config/analysis"
OUT_FILE="$OUT_DIR/entities_snapshot.json"
TMP_FILE="$OUT_DIR/entities_snapshot.tmp.json"
LOCK_DIR="/tmp/export_entities_snapshot.lock"

# zabrání paralelnímu běhu (např. při startu + časovém triggeru)
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  exit 0
fi
trap 'rmdir "$LOCK_DIR" >/dev/null 2>&1 || true' EXIT INT TERM

mkdir -p "$OUT_DIR"

if [ ! -f "$REGISTRY_FILE" ]; then
  echo "Entity registry not found: $REGISTRY_FILE" >&2
  exit 1
fi

python3 <<'PY'
import json
from pathlib import Path

registry_path = Path('/config/.storage/core.entity_registry')
out_path = Path('/config/analysis/entities_snapshot.tmp.json')

raw = json.loads(registry_path.read_text(encoding='utf-8'))
entities = raw.get('data', {}).get('entities', [])

result = []
for e in entities:
    result.append(
        {
            'entity_id': e.get('entity_id'),
            'platform': e.get('platform'),
            'device_id': e.get('device_id'),
            'config_entry_id': e.get('config_entry_id'),
            'original_name': e.get('original_name'),
            'disabled_by': e.get('disabled_by'),
            'hidden_by': e.get('hidden_by'),
            'entity_category': e.get('entity_category'),
            'has_entity_name': e.get('has_entity_name'),
            'original_device_class': e.get('original_device_class'),
            'unique_id': e.get('unique_id'),
        }
    )

result.sort(key=lambda x: (x.get('entity_id') or ''))
out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
PY

# pokud se nic nezměnilo, skonči bez přepsání cílového souboru
if [ -f "$OUT_FILE" ] && cmp -s "$TMP_FILE" "$OUT_FILE"; then
  rm -f "$TMP_FILE"
  exit 0
fi

mv "$TMP_FILE" "$OUT_FILE"
