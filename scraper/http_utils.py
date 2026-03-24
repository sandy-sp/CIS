from __future__ import annotations

import warnings
from typing import Any

import requests
from urllib3.exceptions import InsecureRequestWarning


def get_with_ssl_fallback(url: str, **kwargs: Any) -> requests.Response:
    try:
        return requests.get(url, **kwargs)
    except requests.exceptions.SSLError:
        fallback_kwargs = dict(kwargs)
        fallback_kwargs["verify"] = False
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", InsecureRequestWarning)
            return requests.get(url, **fallback_kwargs)
