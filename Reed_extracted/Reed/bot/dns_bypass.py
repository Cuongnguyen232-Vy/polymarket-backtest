"""
dns_bypass.py — Bypass DNS chặn của nhà mạng VN
══════════════════════════════════════════════════
Import file này ở đầu bất kỳ script nào cần truy cập Polymarket.
Nó sẽ ép Python dùng Google DNS (8.8.8.8) thay vì DNS router.
"""

import socket
import dns.resolver

# Tạo resolver dùng Google DNS
_google_resolver = dns.resolver.Resolver()
_google_resolver.nameservers = ['8.8.8.8', '8.8.4.4']

# Cache DNS để không phải resolve lại mỗi lần
_dns_cache = {}

_original_getaddrinfo = socket.getaddrinfo

def _patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    """Override DNS resolution to use Google DNS for blocked domains."""
    blocked_domains = ['polymarket.com', 'gamma-api.polymarket.com', 
                       'clob.polymarket.com', 'ws-subscriptions-clob.polymarket.com']
    
    needs_bypass = any(host.endswith(d) for d in blocked_domains)
    
    if needs_bypass:
        if host not in _dns_cache:
            try:
                answers = _google_resolver.resolve(host, 'A')
                _dns_cache[host] = str(answers[0])
            except Exception:
                return _original_getaddrinfo(host, port, family, type, proto, flags)
        
        ip = _dns_cache[host]
        return _original_getaddrinfo(ip, port, family, type, proto, flags)
    
    return _original_getaddrinfo(host, port, family, type, proto, flags)

# Monkey-patch socket
socket.getaddrinfo = _patched_getaddrinfo
