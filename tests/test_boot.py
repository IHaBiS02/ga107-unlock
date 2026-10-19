"""Check generated boot configuration without installing it or loading modules."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('inspect_initramfs', ROOT/'tools/inspect_initramfs.py')
inspector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inspector)


class BootTests(unittest.TestCase):
    def test_kernel_selection_and_idempotence(self):
        for present in (True,False):
            with self.subTest(module_installed=present):
                script = '''set -eu
modinfo() { return RETURN_CODE; }
MODULES=(i915 nvidia nvidia_modeset nvidia_uvm nvidia_drm)
HOOKS=(base systemd autodetect kms)
source "$1"
source "$1"
printf '%s\n' "${MODULES[*]}" "${HOOKS[*]}"
'''.replace('RETURN_CODE','0' if present else '1')
                result = subprocess.check_output(['bash','-c',script,'bash',
                    str(ROOT/'boot/zz-ga107-unlock.conf')],text=True).splitlines()
                self.assertEqual(result[0], 'i915 '+('ga107_unlock ' if present else '')+
                                 'nvidia nvidia_modeset nvidia_uvm nvidia_drm')
                self.assertEqual(result[1], 'base systemd autodetect kms'+
                                 (' ga107-order' if present else ''))

    def test_image_only_unit_and_reader(self):
        with tempfile.TemporaryDirectory() as d:
            script = '''set -eu
root=$1
add_module() { [[ $1 == ga107_unlock ]]; }
add_file() { mkdir -p "$root$(dirname "$2")"; cat > "$root$2"; }
add_symlink() { mkdir -p "$root$(dirname "$1")"; ln -s "$2" "$root$1"; }
source "$2"
build
'''
            subprocess.run(['bash','-c',script,'bash',d,
                            str(ROOT/'boot/ga107-order.install')],check=True)
            unit=Path(d)/'usr/lib/systemd/system/ga107-unlock.service'
            text=unit.read_text()
            self.assertIn('Before=sysinit.target systemd-modules-load.service systemd-udevd.service systemd-udev-trigger.service',text)
            subprocess.run(['systemd-analyze','verify',str(unit)],check=True)
            def cpio(entries):
                out=bytearray()
                for name,data in [*entries,('TRAILER!!!',b'')]:
                    raw=name.encode()+b'\0'
                    fields=[0,0o100644,0,0,1,0,len(data),0,0,0,0,len(raw),0]
                    out+=b'070701'+b''.join(f'{v:08x}'.encode() for v in fields)
                    out+=raw+b'\0'*((-(110+len(raw)))%4)+data+b'\0'*((-len(data))%4)
                return out
            early=cpio([('early_cpio',b'1')])
            early+=b'\0'*((-len(early))%512)
            entries=[('etc/modules-load.d/MODULES.conf',b'ga107_unlock\nnvidia\n'),
                     ('usr/lib/systemd/system/ga107-unlock.service',unit.read_bytes()),
                     ('usr/lib/systemd/system/sysinit.target.wants/ga107-unlock.service',b'../ga107-unlock.service')]
            image=Path(d)/'fixture.img'
            image.write_bytes(early+subprocess.check_output(['zstd','-qc'],input=cpio(entries)))
            actual=inspector.inspect(image)
            self.assertEqual(actual,{name:data.decode() for name,data in entries})
            result=subprocess.run(['python3',str(ROOT/'tools/inspect_initramfs.py'),str(image)],
                                  capture_output=True,text=True,check=True)
            self.assertIn('Boot ordering configuration: PASS',result.stdout)
