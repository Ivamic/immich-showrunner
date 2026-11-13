# Security policy

## Supported versions

immich-showrunner is in early development. Security fixes are made only for the latest release.

## Reporting a vulnerability

Please **do not** open a public issue for a security problem.

Report it privately through GitHub:
[Report a vulnerability](https://github.com/Ivamic/immich-showrunner/security/advisories/new)
(the **Security** tab of the repository → **Report a vulnerability**).

Please include:

- the version of immich-showrunner, of Immich and of the media server;
- what an attacker can do and under which conditions (for example, network access to the app,
  a user of the media server, a person who can share an album with the app's Immich user);
- steps to reproduce or a proof of concept.

You can expect a first answer within a week. Once the problem is fixed and a release is out,
the advisory is published, with credit to you if you wish.

## Scope

Of particular interest: anything that makes the app write, move or delete files outside its own
output folder; links that point outside the configured Immich library; access to the Immich API
key or to the web page without signing in; and videos of an album that was never shared with the
app showing up in the media server.
