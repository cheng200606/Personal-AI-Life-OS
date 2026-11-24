# Security Policy

## Reporting a vulnerability

Please do not report security vulnerabilities in public issues. Contact the repository owner through the GitHub profile and include reproduction steps, affected versions, and potential impact. A private reporting address will be added when a dedicated security contact is configured.

## Data handling principles

- Source sync is user-authorized and limited to selected files and connectors.
- Imported content is untrusted input and must not be interpreted as executable instructions.
- Credentials and provider keys belong in environment variables or managed secret storage, never source control.
- User data must be tenant-scoped, exportable, and deletable.
- Logs must not include raw chat text, image content, access tokens, or agent memory content.
