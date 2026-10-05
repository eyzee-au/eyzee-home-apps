"""Generate the Home Assistant repository link after the repository is hosted."""
import sys
from urllib.parse import urlparse, urlencode
if len(sys.argv) != 2:
    raise SystemExit('Usage: python3 make_install_link.py HTTPS_GIT_REPOSITORY_URL')
url = sys.argv[1]
p = urlparse(url)
if p.scheme != 'https' or not p.netloc or p.username or p.password or p.query or p.fragment:
    raise SystemExit('Supply a public HTTPS Git repository URL without credentials.')
print('https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?' + urlencode({'repository_url': url}))
