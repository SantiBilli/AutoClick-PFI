"""Prepare the worker identity and run the API against a configured Ollama server."""
import base64
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlparse


def prepare_runtime(directory: Path) -> dict[str, str]:
    environment = dict(os.environ)
    if not environment.get('AUTOCLICK_CLOUD_API_URL', '').startswith('https://'):
        raise ValueError('HTTPS cloud authorization is required')
    ollama_url = urlparse(environment.get('OLLAMA_BASE_URL', ''))
    if ollama_url.scheme not in {'http', 'https'} or not ollama_url.netloc:
        raise ValueError('An explicit Ollama HTTP(S) URL is required')
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    for variable, filename in (
        ('WORKER_CERT_B64', 'worker.pem'),
        ('WORKER_KEY_B64', 'worker-key.pem'),
    ):
        value = environment.pop(variable, '')
        if not value:
            raise ValueError(f'Missing runtime secret: {variable}')
        payload = base64.b64decode(value, validate=True)
        if not payload.startswith(b'-----BEGIN ') or len(payload) > 32768:
            raise ValueError(f'Invalid runtime secret: {variable}')
        target = directory / filename
        with target.open('wb') as output:
            os.chmod(target, 0o600)
            output.write(payload)
    flags = []
    for variable, flag in (
        ('WORKER_TRUST_ANCHOR_ARN', '--trust-anchor-arn'),
        ('WORKER_PROFILE_ARN', '--profile-arn'),
        ('WORKER_ROLE_ARN', '--role-arn'),
    ):
        value = environment.get(variable, '')
        if not re.fullmatch(r'arn:aws:[a-z0-9:/_-]+', value):
            raise ValueError(f'Invalid AWS identifier: {variable}')
        flags.extend([flag, value])
    config = directory / 'aws-config'
    command = ('/usr/local/bin/aws_signing_helper credential-process '
               f'--certificate {directory}/worker.pem --private-key {directory}/worker-key.pem '
               + ' '.join(flags) + ' --session-duration 900')
    config.write_text('[profile autoclick-worker]\nregion = us-east-1\n'
                      f'credential_process = {command}\n', encoding='utf-8')
    os.chmod(config, 0o600)
    environment['AWS_CONFIG_FILE'] = str(config)
    environment['AUTOCLICK_CLOUD_AWS_PROFILE'] = 'autoclick-worker'
    environment['AWS_EC2_METADATA_DISABLED'] = 'true'
    environment['PYTHONUNBUFFERED'] = '1'
    return environment


def main() -> int:
    try:
        environment = prepare_runtime(Path('/run/autoclick'))
        # Replace PID 1 so Uvicorn receives container shutdown signals directly.
        os.execvpe(sys.executable, [
            sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '0.0.0.0',
            '--port', '8001', '--workers', '1', '--proxy-headers',
        ], environment)
        return 0
    except Exception as error:
        # Do not dump credential helper output or environment contents.
        print(f'Runtime configuration failed ({type(error).__name__}).', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
