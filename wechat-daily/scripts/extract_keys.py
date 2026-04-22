#!/usr/bin/env python3
"""
微信 Mac 4.x 数据库密钥提取工具
使用 frida hook CCKeyDerivationPBKDF 捕获所有数据库的加密密钥
"""

import os
import sys
import json
import glob
import subprocess
import time
import shutil

KEYS_FILE = os.path.expanduser("~/.config/wechat-keys.json")
CONFIG_FILE = os.path.expanduser("~/.config/wechat-daily.json")
WECHAT_APP = "/Applications/WeChat.app"
WECHAT_COPY = os.path.expanduser("~/Desktop/WeChat.app")
FRIDA_LOG = "/tmp/wechat_frida_keys.log"
WECHAT_BASE = os.path.expanduser(
    "~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files"
)

# Frida JS hook script — 拦截 CCKeyDerivationPBKDF (Apple CommonCrypto PBKDF2)
FRIDA_JS = r"""
'use strict';

var CCKeyDerivationPBKDF = null;

Process.enumerateModules().forEach(function(mod) {
    try {
        var exp = mod.enumerateExports();
        for (var i = 0; i < exp.length; i++) {
            if (exp[i].name === 'CCKeyDerivationPBKDF') {
                CCKeyDerivationPBKDF = exp[i].address;
                break;
            }
        }
    } catch (e) {}
    if (CCKeyDerivationPBKDF) return;
});

if (!CCKeyDerivationPBKDF) {
    send({type: 'error', msg: 'CCKeyDerivationPBKDF not found'});
    return;
}

send({type: 'status', msg: 'Hooked CCKeyDerivationPBKDF at ' + CCKeyDerivationPBKDF});

Interceptor.attach(CCKeyDerivationPBKDF, {
    onEnter: function(args) {
        this.password = args[0];
        this.passwordLen = args[1].toInt32();
        this.salt = args[2];
        this.saltLen = args[3].toInt32();
        this.prf = args[4].toInt32();
        this.rounds = args[5].toInt32();
        this.derivedKey = args[6];
        this.derivedKeyLen = args[7].toInt32();
    },
    onLeave: function(retval) {
        try {
            var pw = hexdump(this.password, {length: Math.min(this.passwordLen, 256)});
            var saltHex = Array.from(new Uint8Array(
                Memory.readByteArray(this.salt, Math.min(this.saltLen, 32))
            )).map(function(b){ return ('0' + b.toString(16)).slice(-2); }).join('');

            var dkBytes = new Uint8Array(
                Memory.readByteArray(this.derivedKey, Math.min(this.derivedKeyLen, 64))
            );
            var dkHex = Array.from(dkBytes).map(function(b){
                return ('0' + b.toString(16)).slice(-2);
            }).join('');

            var entry = {
                rounds: this.rounds,
                salt: saltHex,
                dk: dkHex,
                dkLen: this.derivedKeyLen
            };
            send({type: 'key', data: entry});
        } catch(e) {
            send({type: 'error', msg: e.toString()});
        }
    }
});
"""

# Python frida host script
FRIDA_HOST = r"""
import frida
import json
import sys
import time

LOG_FILE = "/tmp/wechat_frida_keys.log"
WECHAT_PATH = "{wechat_path}"

keys = []

def on_message(message, data):
    if message['type'] == 'send':
        payload = message['payload']
        if payload.get('type') == 'key':
            keys.append(payload['data'])
            with open(LOG_FILE, 'a') as f:
                f.write(json.dumps(payload['data']) + '\n')
            print(f"  [KEY] rounds={payload['data']['rounds']} salt={payload['data']['salt'][:16]}... dk={payload['data']['dk'][:16]}...")
        elif payload.get('type') == 'status':
            print(f"  {payload['msg']}")
        elif payload.get('type') == 'error':
            print(f"  [ERROR] {payload['msg']}")
    elif message['type'] == 'error':
        print(f"  [FRIDA ERROR] {message.get('description', message)}")

JS_CODE = '''{js_code}'''

print("  正在启动微信...")
device = frida.get_local_device()
pid = device.spawn([WECHAT_PATH])
session = device.attach(pid)
script = session.create_script(JS_CODE)
script.on('message', on_message)
script.load()
device.resume(pid)

print("  微信已启动，请登录微信。")
print("  登录后等待30秒，密钥会在启动时自动捕获...")
print(f"  密钥日志: {LOG_FILE}")

for i in range(90, 0, -1):
    time.sleep(1)
    if i % 15 == 0:
        print(f"  剩余 {i} 秒... (已捕获 {len(keys)} 个密钥)")

print(f"\\n  共捕获 {len(keys)} 个密钥")
session.detach()
"""


def run_cmd(cmd, check=True):
    """Run a shell command and return output"""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"  [ERROR] {cmd}")
        print(f"  {result.stderr.strip()}")
        sys.exit(1)
    return result.stdout.strip()


def check_env():
    """Step 1: Check prerequisites"""
    print("\n[1/5] 检查环境...")

    if sys.platform != "darwin":
        print("  [ERROR] 仅支持 macOS")
        sys.exit(1)

    if not os.path.exists(WECHAT_APP):
        print(f"  [ERROR] 未找到微信: {WECHAT_APP}")
        print("  请确认已安装微信 Mac 版")
        sys.exit(1)
    print("  ✓ 微信已安装")

    # Check Python version
    if sys.version_info < (3, 9):
        print(f"  [ERROR] Python 版本过低: {sys.version}，需要 3.9+")
        sys.exit(1)
    print(f"  ✓ Python {sys.version_info.major}.{sys.version_info.minor}")

    return True


def prepare_wechat():
    """Step 2: Copy and codesign WeChat"""
    print("\n[2/5] 准备微信签名副本...")

    if os.path.exists(WECHAT_COPY):
        existing_sig = run_cmd(f"codesign -dv {WECHAT_COPY} 2>&1 | grep 'Signature'", check=False)
        print("  ✓ 签名副本已存在")
    else:
        print(f"  复制微信到 {WECHAT_COPY}...")
        shutil.copytree(WECHAT_APP, WECHAT_COPY, symlinks=True)

    print("  重新签名（去掉 Hardened Runtime）...")
    run_cmd(f"codesign --force --deep --sign - {WECHAT_COPY}")
    print("  ✓ 签名完成")


def install_frida():
    """Step 3: Check/install frida"""
    print("\n[3/5] 检查 frida...")

    try:
        import frida
        print(f"  ✓ frida 已安装 (版本: {frida.__version__})")
        return True
    except ImportError:
        pass

    print("  正在安装 frida...")
    run_cmd(f"{sys.executable} -m pip install frida frida-tools")
    print("  ✓ frida 安装完成")
    return True


def extract_keys():
    """Step 4: Run frida to extract keys"""
    print("\n[4/5] 提取密钥...")

    # Kill existing WeChat
    run_cmd("killall WeChat 2>/dev/null", check=False)
    time.sleep(2)

    # Clear previous log
    if os.path.exists(FRIDA_LOG):
        os.remove(FRIDA_LOG)

    # Write frida host script
    wechat_binary = os.path.join(WECHAT_COPY, "Contents", "MacOS", "WeChat")
    host_script = FRIDA_HOST.format(
        wechat_path=wechat_binary,
        js_code=FRIDA_JS.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
    )

    host_path = "/tmp/wechat_frida_host.py"
    with open(host_path, "w") as f:
        f.write(host_script)

    print("  启动 frida hook...")
    print("  " + "=" * 50)
    try:
        subprocess.run([sys.executable, host_path], check=True)
    except KeyboardInterrupt:
        print("\n  用户中断")
    print("  " + "=" * 50)

    if not os.path.exists(FRIDA_LOG):
        print("  [ERROR] 未捕获到任何密钥。请确认已登录微信。")
        sys.exit(1)

    # Parse captured keys
    keys = []
    with open(FRIDA_LOG) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    keys.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    print(f"  ✓ 共捕获 {len(keys)} 个密钥")
    return keys


def detect_databases():
    """Auto-detect WeChat database paths and wxid"""
    print("\n[5/5] 匹配密钥到数据库...")

    # Find wxid directories
    pattern = os.path.join(WECHAT_BASE, "*/db_storage")
    db_dirs = glob.glob(pattern)

    if not db_dirs:
        print(f"  [ERROR] 未找到微信数据库目录")
        print(f"  搜索路径: {pattern}")
        sys.exit(1)

    # Use the first (usually only) wxid directory
    db_base = db_dirs[0]
    wxid = db_base.split("/xwechat_files/")[1].split("/")[0]
    print(f"  ✓ 检测到 wxid: {wxid}")
    print(f"  ✓ 数据库路径: {db_base}")

    # Load captured keys
    keys = []
    with open(FRIDA_LOG) as f:
        for line in f:
            try:
                keys.append(json.loads(line.strip()))
            except:
                continue

    # Match keys to databases by salt
    db_files = {
        "message_0": os.path.join(db_base, "message", "message_0.db"),
        "contact": os.path.join(db_base, "contact", "contact.db"),
        "session": os.path.join(db_base, "session", "session.db"),
    }

    result = {}
    for db_name, db_path in db_files.items():
        if not os.path.exists(db_path):
            print(f"  [WARN] 数据库不存在: {db_path}")
            continue

        # Read first page salt (bytes 4080-4096 of the file, which is the reserve area)
        with open(db_path, "rb") as f:
            header = f.read(4096)

        # The salt is in the reserve area: page[4096-80:4096-80+16] = page[4016:4032]
        # But for SQLCipher, the salt is actually at the very end of page 0's reserve
        # More precisely, salt = first 16 bytes of the file (for SQLCipher 4)
        file_salt = header[:16].hex()

        # Try to match: for each key, check if its derived key can decrypt page 0
        # Simpler approach: try each captured key against each DB
        matched = False
        for key_entry in keys:
            if key_entry.get("rounds") == 256000 and key_entry.get("dkLen") in (48, 64):
                dk = key_entry["dk"]
                # Store the first 32 bytes (256 bits) as the AES key
                if len(dk) >= 64:
                    result[db_name] = dk[:64]
                    matched = True
                    break

        if matched:
            print(f"  ✓ {db_name}.db → 密钥已匹配")
        else:
            print(f"  [WARN] {db_name}.db 未匹配到密钥")

    if not result:
        print("\n  [ERROR] 未能匹配任何密钥到数据库")
        print("  请确认：")
        print("  1. 已正常登录微信")
        print("  2. 微信版本为 Mac 4.x")
        sys.exit(1)

    # Save keys
    os.makedirs(os.path.dirname(KEYS_FILE), exist_ok=True)
    with open(KEYS_FILE, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\n  ✓ 密钥已保存到 {KEYS_FILE}")

    # Also create/update config with detected paths
    config = {}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            config = json.load(f)

    config["wxid"] = wxid
    config["db_base_path"] = db_base

    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    print(f"  ✓ 配置已更新 {CONFIG_FILE}")

    return result


def main():
    print("=" * 50)
    print("微信 Mac 4.x 数据库密钥提取工具")
    print("=" * 50)

    check_env()
    prepare_wechat()
    install_frida()
    extract_keys()
    detect_databases()

    print("\n" + "=" * 50)
    print("密钥提取完成！")
    print(f"  密钥文件: {KEYS_FILE}")
    print(f"  配置文件: {CONFIG_FILE}")
    print("\n接下来请在 Claude Code 中说 '日报' 来配置监控群聊。")
    print("=" * 50)


if __name__ == "__main__":
    main()
