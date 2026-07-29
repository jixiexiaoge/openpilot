# MAPD implementation by pfeiferj

This bundled `mapd` is built from upstream v2.0.6 with its Go `gomsgq` header
configured for IQ.Pilot's `NUM_READERS = 32`. The upstream release binary uses
15 readers, which makes its shared-memory payload offset incompatible with
IQ.Pilot and prevents valid `mapdOut` publication.

https://github.com/pfeiferj/openpilot-mapd/releases/
