# Third-party licenses

OVManager is MIT-licensed, but its dependencies, base images, system packages, optional tools, icons, and other assets retain their own licenses.

Release artifacts must include an automatically generated software bill of materials and all notices required by shipped components. Package manifests are the current dependency source of truth:

- Python: `pyproject.toml` and `uv.lock`
- JavaScript: `frontend/package.json` and `frontend/package-lock.json`
- Container: `Dockerfile` and its resolved base-image digest

A dependency must not be approved solely from its package name. Release automation must resolve the exact version and authoritative license metadata, flag unknown/custom/non-commercial licenses for review, and preserve required notices. Generated inventories should replace or accompany this file for each release.
