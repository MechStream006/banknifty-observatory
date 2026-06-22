"""
lib.discovery — BankNifty Observatory Discovery Infrastructure
==============================================================

Short-lived empirical measurement subsystem used to obtain real SmartAPI
observations before committing to production schema design (M4B).

Scope
-----
Discovery phase (M4A) only. This module is NOT for use in production
collection, derivation, research, or persistence modules. It is destroyed
(or archived) once the discovery phase is complete and the production
schema is ratified.

Isolation enforcement
---------------------
The structural isolation test at:
    tests/unit/test_discovery/test_structural_isolation.py

asserts that no file under acquisition/, derivation/, research/,
persistence/, integrity/, curation/, or lib/ (outside this package)
imports from lib.discovery. Violating this constraint is a build failure.

Permitted callers: scripts/, tests/unit/test_discovery/

Component availability by milestone
------------------------------------
M4A-1  lib.discovery._errors, lib.discovery._models          [COMPLETE]
M4A-2  lib.discovery.scheduler                               [COMPLETE]
       lib.discovery.metrics, lib.discovery.failures         [PENDING]
M4A-3  lib.discovery.archiver                                [COMPLETE]
       lib.discovery.store                                   [PENDING]
M4A-4  lib.discovery.session                                 [COMPLETE]
       lib.discovery.fetchers.chain                          [COMPLETE]
       lib.discovery.fetchers.spot                           [COMPLETE]
M4A-5  lib.discovery.controller                              [COMPLETE]
       lib.discovery._validators                             [PENDING]
M4A-6  lib.discovery.report                                  [PENDING]
"""
