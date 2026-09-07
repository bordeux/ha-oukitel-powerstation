# Changelog

## [0.3.4](https://github.com/bordeux/ha-oukitel-powerstation/compare/v0.3.3...v0.3.4) (2026-09-07)


### Bug Fixes

* detect and recover when the station stops streaming telemetry ([964dd3d](https://github.com/bordeux/ha-oukitel-powerstation/commit/964dd3d3a1db81b281e2b2af41fae773c085704b))
* detect and recover when the station stops streaming telemetry ([99d941c](https://github.com/bordeux/ha-oukitel-powerstation/commit/99d941cf8d11014c817033236510a34c81e196a2)), closes [#6](https://github.com/bordeux/ha-oukitel-powerstation/issues/6)

## [0.3.3](https://github.com/bordeux/ha-oukitel-powerstation/compare/v0.3.2...v0.3.3) (2026-09-07)


### Bug Fixes

* name the AC/DC input sensors as charging input power ([e061e68](https://github.com/bordeux/ha-oukitel-powerstation/commit/e061e68f867f89343791c1ed1fbde75b08c5f2ee))
* name the AC/DC input sensors as charging input power ([844f369](https://github.com/bordeux/ha-oukitel-powerstation/commit/844f3690b66363c9636753bcc7a18ea9ca32b7f1)), closes [#12](https://github.com/bordeux/ha-oukitel-powerstation/issues/12)

## [0.3.2](https://github.com/bordeux/ha-oukitel-powerstation/compare/v0.3.1...v0.3.2) (2026-09-02)


### Bug Fixes

* bound cloud HTTP requests and surface transport errors ([c341733](https://github.com/bordeux/ha-oukitel-powerstation/commit/c341733dfe5d31bf1b0e5a8425e9a40e395223d8)), closes [#6](https://github.com/bordeux/ha-oukitel-powerstation/issues/6)
* stop transport errors escaping the cloud and local paths ([49a4de4](https://github.com/bordeux/ha-oukitel-powerstation/commit/49a4de40c2242b1adc9fd2d10d9a1c2c099c53cb))
* surface local socket errors so the coordinator can recover ([26af41e](https://github.com/bordeux/ha-oukitel-powerstation/commit/26af41e84797fe4071865dc0ae16d2ea832c81bd))

## [0.3.1](https://github.com/bordeux/ha-oukitel-powerstation/compare/v0.3.0...v0.3.1) (2026-09-02)


### Bug Fixes

* answer device pings to keep the local connection alive ([0cbc136](https://github.com/bordeux/ha-oukitel-powerstation/commit/0cbc1369f0d31cffa3581ca196f2d0d15a9d4429))
* answer device pings to keep the local connection alive ([7504dcc](https://github.com/bordeux/ha-oukitel-powerstation/commit/7504dcc8f423242bf0b9df37a256a7b3b7900d44)), closes [#7](https://github.com/bordeux/ha-oukitel-powerstation/issues/7)

## [0.3.0](https://github.com/bordeux/ha-oukitel-powerstation/compare/v0.2.2...v0.3.0) (2026-06-16)


### Features

* optional cloud poll for temperature and voltage ([f04dae1](https://github.com/bordeux/ha-oukitel-powerstation/commit/f04dae10cb79640a42c872f5d78f3d4acd234d48))

## [0.2.2](https://github.com/bordeux/ha-oukitel-powerstation/compare/v0.2.1...v0.2.2) (2026-06-16)


### Bug Fixes

* keep device streaming by re-arming subscription, replace struct state ([44d081c](https://github.com/bordeux/ha-oukitel-powerstation/commit/44d081c5e6911ae3595fbf47f7dc0ef942e5cace))

## [0.2.1](https://github.com/bordeux/ha-oukitel-powerstation/compare/v0.2.0...v0.2.1) (2026-06-16)


### Bug Fixes

* bound connect/handshake and don't recover on cancel ([dcf7e24](https://github.com/bordeux/ha-oukitel-powerstation/commit/dcf7e24f62b4ff3290c8f8cc312456372b24e0f7))

## [0.2.0](https://github.com/bordeux/ha-oukitel-powerstation/compare/v0.1.0...v0.2.0) (2026-06-16)


### Features

* add per-port power sensors (AC/USB/Type-C/DC) ([c31e662](https://github.com/bordeux/ha-oukitel-powerstation/commit/c31e662f835aac168b716ce1a9fa52b1028c897d))
* initial Oukitel Power Station Home Assistant integration ([444d3eb](https://github.com/bordeux/ha-oukitel-powerstation/commit/444d3eb1adcfb9f3a779e0906cbae9a9d85d305f))


### Bug Fixes

* import DeviceInfo from device_registry ([8f2b41f](https://github.com/bordeux/ha-oukitel-powerstation/commit/8f2b41fb8c6e8b9e96ea3d2e060f7f5849a6e60f))
* keep telemetry live with keepalive ping and read watchdog ([0aa1d36](https://github.com/bordeux/ha-oukitel-powerstation/commit/0aa1d36385ead8b89838d36da14a88aff57c1442))
