# Changelog

## [0.1.2](https://github.com/KinjiKawaguchi/minport-py/compare/v0.1.1...v0.1.2) (2026-04-17)


### Bug Fixes

* detect circular imports via transitive load analysis ([#33](https://github.com/KinjiKawaguchi/minport-py/issues/33)) ([aff7052](https://github.com/KinjiKawaguchi/minport-py/commit/aff7052defd09e36c19b4e611f04cfbc2e297025))

## [0.1.1](https://github.com/KinjiKawaguchi/minport-py/compare/v0.1.0...v0.1.1) (2026-04-12)


### Bug Fixes

* preserve inline comments when rewriting imports ([#30](https://github.com/KinjiKawaguchi/minport-py/issues/30)) ([4a8931f](https://github.com/KinjiKawaguchi/minport-py/commit/4a8931fd8a5c16ef6932664d9eb39c034a351f22))

## 0.1.0 (2026-04-12)


### Features

* add --extend-exclude option ([#20](https://github.com/KinjiKawaguchi/minport-py/issues/20)) ([#22](https://github.com/KinjiKawaguchi/minport-py/issues/22)) ([f5c8fb9](https://github.com/KinjiKawaguchi/minport-py/commit/f5c8fb98780b0574a7bea557b059f7c23b64f13f))
* add default exclude patterns like Ruff ([#23](https://github.com/KinjiKawaguchi/minport-py/issues/23)) ([f4abb8b](https://github.com/KinjiKawaguchi/minport-py/commit/f4abb8b5f811c2b9d8f23dcd24c973c7e4278d29))
* **cli:** always show summary line and add --quiet flag ([8a2bcaf](https://github.com/KinjiKawaguchi/minport-py/commit/8a2bcafbe575a771e7e0b2060210943a81a7ada9)), closes [#5](https://github.com/KinjiKawaguchi/minport-py/issues/5)
* **cli:** always show summary line and add --quiet flag ([#11](https://github.com/KinjiKawaguchi/minport-py/issues/11)) ([cb52893](https://github.com/KinjiKawaguchi/minport-py/commit/cb528932fb606e892faf673c90f7efc8d57e94cd))
* complete minport with 115 tests at 100% coverage ([efd0b47](https://github.com/KinjiKawaguchi/minport-py/commit/efd0b4737f81efda2dd2a920d72fb1c1911cade8))
* resolve wildcard re-exports recursively ([#14](https://github.com/KinjiKawaguchi/minport-py/issues/14)) ([02d1a5e](https://github.com/KinjiKawaguchi/minport-py/commit/02d1a5eee324c469b09c09702950b047aa645b15))
* resolve wildcard re-exports recursively (closes [#8](https://github.com/KinjiKawaguchi/minport-py/issues/8)) ([36c8775](https://github.com/KinjiKawaguchi/minport-py/commit/36c877526a16b72cfcb35af1ad2f208ef9866f4c))
* support per-name `# minport: ignore` in multi-line imports ([#25](https://github.com/KinjiKawaguchi/minport-py/issues/25)) ([455b71c](https://github.com/KinjiKawaguchi/minport-py/commit/455b71cfb274d8fbee56a84b050ec80170da7223))
* walk except* blocks for nested re-exports ([b08a1c6](https://github.com/KinjiKawaguchi/minport-py/commit/b08a1c6861e3dd1ac73303895026af1b56a20852))


### Bug Fixes

* **_fixer:** count only real rewrites in fixes_applied ([ee9d8d6](https://github.com/KinjiKawaguchi/minport-py/commit/ee9d8d6a1ee644db1e18c2499c9ed92ab2716dd3)), closes [#16](https://github.com/KinjiKawaguchi/minport-py/issues/16)
* **_fixer:** count only real rewrites in fixes_applied ([#17](https://github.com/KinjiKawaguchi/minport-py/issues/17)) ([08ae79b](https://github.com/KinjiKawaguchi/minport-py/commit/08ae79b0da956eee79eff90e57b49f5b30989ecd)), closes [#16](https://github.com/KinjiKawaguchi/minport-py/issues/16)
* **cli:** tighten fix-output test and sync CLAUDE.md with new summary format ([d17841a](https://github.com/KinjiKawaguchi/minport-py/commit/d17841a394f50a03ca6c361440539ecc122dd2ef))
* inline ast.TypeAlias append to keep coverage 100% on 3.11 ([a89a38c](https://github.com/KinjiKawaguchi/minport-py/commit/a89a38c8e1bea3cfebfc13889869fc1f0c4ca245))
* preserve tab indent and refuse rewrites with trailing code ([71c9558](https://github.com/KinjiKawaguchi/minport-py/commit/71c955837a7d9ea68f3193e7371593e663198f4b))
* rebuild multi-name from-imports via AST to stop data loss on --fix ([49bb527](https://github.com/KinjiKawaguchi/minport-py/commit/49bb52721321669680bc1ed2b4c1c2718bb67d83)), closes [#2](https://github.com/KinjiKawaguchi/minport-py/issues/2)
* rebuild multi-name from-imports via AST to stop data loss on --fix ([#13](https://github.com/KinjiKawaguchi/minport-py/issues/13)) ([267be93](https://github.com/KinjiKawaguchi/minport-py/commit/267be93ffd3ada483e32e3e3857fa36a8f9e1672))
* recognize annotated assignment re-exports and update docs ([b60ba78](https://github.com/KinjiKawaguchi/minport-py/commit/b60ba78b50f8ad1ab9b06ad483020095c41a4fa2))
* recognize assignment re-exports listed in __all__ ([6298620](https://github.com/KinjiKawaguchi/minport-py/commit/6298620c12d518fedc6c1d31431ba5752124a56d)), closes [#7](https://github.com/KinjiKawaguchi/minport-py/issues/7)
* recognize assignment re-exports listed in __all__ ([#9](https://github.com/KinjiKawaguchi/minport-py/issues/9)) ([efde96a](https://github.com/KinjiKawaguchi/minport-py/commit/efde96a24e558f41d0f19df83be91e6458e91eba))
* recognize re-exports inside try/except and if-guarded blocks ([182d0c0](https://github.com/KinjiKawaguchi/minport-py/commit/182d0c02a425e333ff5063ba054cd020822f44b0)), closes [#6](https://github.com/KinjiKawaguchi/minport-py/issues/6)
* recognize re-exports inside try/except and if-guarded blocks ([#10](https://github.com/KinjiKawaguchi/minport-py/issues/10)) ([2a11f62](https://github.com/KinjiKawaguchi/minport-py/commit/2a11f626d2a9803972040c50bc871aa926151825))
* resolve ty typecheck error by simplifying check() return type ([614afd5](https://github.com/KinjiKawaguchi/minport-py/commit/614afd5bf66d4dd35821e9eddaafc6395d54eb56))
* skip --fix when rewrite would duplicate an existing import ([4b4aca9](https://github.com/KinjiKawaguchi/minport-py/commit/4b4aca9d6e7f554bd580b1be704ace1f520033a6))
* skip --fix when rewrite would duplicate an existing import ([#12](https://github.com/KinjiKawaguchi/minport-py/issues/12)) ([118c02b](https://github.com/KinjiKawaguchi/minport-py/commit/118c02ba81619023e83ad9cf433253f2fdd236a6))
* skip ancestor package suggestions in __init__.py ([#27](https://github.com/KinjiKawaguchi/minport-py/issues/27)) ([180d1f7](https://github.com/KinjiKawaguchi/minport-py/commit/180d1f7d797f553119f65a290a22f993acc9f206))
* skip self-import suggestions in __init__.py ([#21](https://github.com/KinjiKawaguchi/minport-py/issues/21)) ([c0f8d5a](https://github.com/KinjiKawaguchi/minport-py/commit/c0f8d5a9446fd0b3fa589d8cdece0b11e7889a66))
* strengthen duplicate-fix guard against line-level and cross-line collisions ([bec6ed8](https://github.com/KinjiKawaguchi/minport-py/commit/bec6ed8bac74b260632ac25719f5d24fa2a98161))
* trace re-export origins to stop flagging chains as conflicts ([4a53dc5](https://github.com/KinjiKawaguchi/minport-py/commit/4a53dc5443eab769104b5fc295b5d31579fcc445))
* trace re-export origins to stop flagging chains as conflicts ([#15](https://github.com/KinjiKawaguchi/minport-py/issues/15)) ([0774ff0](https://github.com/KinjiKawaguchi/minport-py/commit/0774ff0c6ad3c1b0e9b2a28b651a9aef1ae8430c))


### Documentation

* update README for v0.1.0 release ([#28](https://github.com/KinjiKawaguchi/minport-py/issues/28)) ([d713f0a](https://github.com/KinjiKawaguchi/minport-py/commit/d713f0a51ddb195bea7cd843592c20f010c44ff0))
