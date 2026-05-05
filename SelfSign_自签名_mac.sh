#!/usr/bin/env bash

set -euo pipefail

# 获取脚本所在目录（即应用包根目录）
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "========================================"
echo "  MaaLostSword macOS 自签名工具"
echo "========================================"
echo ""
echo "目标目录: ${script_dir}"
echo ""

# 1. 移除隔离属性
echo "[1/3] 正在移除隔离属性 (quarantine)..."
xattr -dr com.apple.quarantine "${script_dir}" 2>/dev/null || true
echo "      完成"
echo ""

# 2. 给 Python 可执行文件加权限
echo "[2/3] 正在修复 Python 执行权限..."
if [ -d "${script_dir}/python/bin" ]; then
    chmod +x "${script_dir}/python/bin/"* 2>/dev/null || true
    echo "      完成"
else
    echo "      未找到 python/bin 目录，跳过"
fi
echo ""

# 3. 对 Mach-O / dylib 文件进行 ad-hoc 签名
echo "[3/3] 正在对原生库进行自签名..."
signed_count=0
while IFS= read -r -d '' file; do
    file_info=$(file -b "${file}" 2>/dev/null || true)
    if echo "${file_info}" | grep -qE 'Mach-O|shared library|dynamic library'; then
        if codesign --force --sign - --timestamp=none "${file}" 2>/dev/null; then
            signed_count=$((signed_count + 1))
        fi
    fi
done < <(find "${script_dir}" -type f \( -name '*.dylib' -o -name '*.so' -o -perm +111 \) -print0 2>/dev/null)

echo "      已签名文件数: ${signed_count}"
echo ""

echo "========================================"
echo "  自签名完成，请重新运行应用"
echo "========================================"
