import argparse
import urllib3
import garth

# 核心修复：禁用 SSL 警告，防止警告内容污染 stdout 被 Bash 脚本错误捕获
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("email", nargs="?", help="email of garmin")
    parser.add_argument("password", nargs="?", help="password of garmin")
    parser.add_argument(
        "--is-cn",
        dest="is_cn",
        action="store_true",
        help="if garmin account is cn",
    )
    options = parser.parse_args()

    if options.is_cn:
        garth.configure(domain="garmin.cn", ssl_verify=False)

    garth.login(options.email, options.password)
    secret_string = garth.client.dumps()
    print(secret_string)
