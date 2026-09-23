# Changelog

## [0.7.0](https://github.com/bordeux/ha-oukitel-powerstation/compare/v0.6.0...v0.7.0) (2026-09-23)


### Features

* add Oukitel p1000e plus ([76bc70f](https://github.com/bordeux/ha-oukitel-powerstation/commit/76bc70f07d8c8d697e3568804b46a75e74e14559))
* add Oukitel p1000e plus ([91bd363](https://github.com/bordeux/ha-oukitel-powerstation/commit/91bd363448d4d31821d6ef4173cc75ae8db838d1))
* p11uve is also the Oukitel P1000 Plus (shared product key) ([f476726](https://github.com/bordeux/ha-oukitel-powerstation/commit/f4767267e781c6ecce668a92e8dd27fcd89bc780))

## [0.6.0](https://github.com/bordeux/ha-oukitel-powerstation/compare/v0.5.1...v0.6.0) (2026-09-16)


### Features

* add inverter temp for IEE P2400/P3200 ([5601b0e](https://github.com/bordeux/ha-oukitel-powerstation/commit/5601b0e24a01bcfe883dd72579e8355a3829cf01))
* Add inverter temp for IEE P2400/P3200 ([32c5a2d](https://github.com/bordeux/ha-oukitel-powerstation/commit/32c5a2d83f0566c5bb6c905c69d50610ff626761))
* add manufacturer override ([aba5137](https://github.com/bordeux/ha-oukitel-powerstation/commit/aba51375f09797724cd8654abc83394dbb0e9449))
* exclude LED tag 34 on p11wDf so bms_version can't bind it ([afca8c6](https://github.com/bordeux/ha-oukitel-powerstation/commit/afca8c6c7d60317caa28233f7f5dd38aa89f835e))


### Bug Fixes

* improve cloud login error feedback ([fa10a22](https://github.com/bordeux/ha-oukitel-powerstation/commit/fa10a22615760fce3d9671a5a2ff84fc32f2bb87))

## [0.5.1](https://github.com/bordeux/ha-oukitel-powerstation/compare/v0.5.0...v0.5.1) (2026-09-13)


### Bug Fixes

* correct the p11uve model name to P1500E Plus ([0851214](https://github.com/bordeux/ha-oukitel-powerstation/commit/0851214cebed06c9f8593291e8c80632520928c3))
* correct the p11uve model name to P1500E Plus ([715be92](https://github.com/bordeux/ha-oukitel-powerstation/commit/715be922edb8f500d18924f5c187a0340598a06b))

## [0.5.0](https://github.com/bordeux/ha-oukitel-powerstation/compare/v0.4.0...v0.5.0) (2026-09-12)


### Features

* battery-powered binary sensor, reload button, opt-in control ([6637505](https://github.com/bordeux/ha-oukitel-powerstation/commit/66375052dabede7342f277f2e37b2455b3d08c2c))
* battery-powered binary sensor, reload button, opt-in control ([b58a0ed](https://github.com/bordeux/ha-oukitel-powerstation/commit/b58a0ed181fccbc8aac8713ea21ad5ff40c85529))
* cloud-only stations (monitor a station with no LAN reach) ([96ef447](https://github.com/bordeux/ha-oukitel-powerstation/commit/96ef447762d73f8aad6de7d48bb249dc0b84144d))
* cloud-only stations (monitor a station with no LAN reach) ([6804e2f](https://github.com/bordeux/ha-oukitel-powerstation/commit/6804e2f19a7e1debb416a80233c4e8e3d2fc946c))
* product manifest layer (TSL-driven entities foundation) ([24e856b](https://github.com/bordeux/ha-oukitel-powerstation/commit/24e856bc0deefb87eda62abc90f5f7e31e763250))
* product manifest layer (TSL-driven entities foundation) ([0326935](https://github.com/bordeux/ha-oukitel-powerstation/commit/0326935974569cf4491ef9323b673388d1db7f7e))
* support the OUKITEL P1500 via manifest-gated entities ([6c4e085](https://github.com/bordeux/ha-oukitel-powerstation/commit/6c4e0853862cc1b73d9675b0d7994dbc9585f4ff))
* support the OUKITEL P1500 via manifest-gated entities ([2e9fecd](https://github.com/bordeux/ha-oukitel-powerstation/commit/2e9fecd376ac4a930e2440e8fd8b322a8bc43b30))

## [0.4.0](https://github.com/bordeux/ha-oukitel-powerstation/compare/v0.3.4...v0.4.0) (2026-09-08)


### Features

* integration icon + Polish translations ([aa527e8](https://github.com/bordeux/ha-oukitel-powerstation/commit/aa527e8bc8a8749610b6290bed27fd44d6c4b1d9))


### Bug Fixes

* authKey refresh works for shared accounts (regenerateAuthKey) ([b891f13](https://github.com/bordeux/ha-oukitel-powerstation/commit/b891f133a1da44005c3f2f6b23670b4365021ce1))
* authKey refresh works for shared accounts (regenerateAuthKey) ([b6af7f8](https://github.com/bordeux/ha-oukitel-powerstation/commit/b6af7f884b0b23496560bd734e3f1a7a9b5d4db9))
* fail startup when authKey refresh returns rejected key ([24314a3](https://github.com/bordeux/ha-oukitel-powerstation/commit/24314a330deae817842f1c4cacc4bd0376bba6d0))
* stop authKey ping-pong on shared accounts ([7ac8f2b](https://github.com/bordeux/ha-oukitel-powerstation/commit/7ac8f2b8bb289011e57b2e0ff86b52b1b2c1c57f))

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
