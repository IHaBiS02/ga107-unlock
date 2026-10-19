# SPDX-License-Identifier: GPL-2.0-only
"""Status evidence, shell quoting, and root-argument preservation regressions."""
import importlib.util
from pathlib import Path
import shlex
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location('desktop_' + name, ROOT / 'tools/desktop' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


status, config, installer = (module(name) for name in ('status', 'configure_boot', 'install'))


class DesktopTests(unittest.TestCase):
    def state(self):
        return dict(evidence='post-FLR SEC2 SS0=88888888 SS1=00000008\nga107_unlock: SS0 applied and FLR completed',
                    loaded=True, execute='Y', ss1_full='Y', target=status.TARGET, driver_ok=True,
                    board_matches=True, journal_ok=True, installed_version='test', loaded_version='test',
                    source_version='test', pkgbase='linux-cachyos', missing_firmware=[], state='inactive')

    def test_apply_requires_completion_and_selectors(self):
        s = self.state()
        self.assertEqual(status.evaluate(s)[:2], ('applied', True))
        for field, value in [('evidence', ''), ('ss1_full', 'N'), ('driver_ok', False), ('loaded', False),
                             ('target', '0000:02:00.0')]:
            case = s | {field: value}
            self.assertFalse(status.evaluate(case)[1], field)
        for evidence in [s['evidence'].replace('00000008', '00000007'),
                         s['evidence'] + '\nexperiment failed (-22)']:
            self.assertFalse(status.evaluate(s | dict(evidence=evidence))[1])
        self.assertEqual(status.evaluate(s | dict(journal_ok=False, evidence=''))[0], 'unknown')
        self.assertEqual(status.evaluate(s | dict(board_matches=False))[0], 'unsupported')

    def test_repair_is_quoted_and_syntax_valid(self):
        path = Path("/tmp/source 'with spaces $(echo DO_NOT_EXECUTE)")
        text = status.repair_commands(self.state(), path)
        argv = shlex.split(text)
        self.assertEqual(argv[:2], ['bash', '-c'])
        self.assertIn('cd ' + shlex.quote(str(path)), argv[2])
        subprocess.run(['bash', '-n', '-c', argv[2]], check=True)
        self.assertIn('limine-mkinitcpio', argv[2])
        self.assertNotIn('insmod', argv[2])
        self.assertNotIn('systemctl poweroff', argv[2])
        self.assertIn('fetch_artifacts.py', status.repair_commands(self.state() | dict(missing_firmware=['x'])))
        self.assertNotIn('make module', status.repair_commands(self.state() | dict(pkgbase='linux-cachyos-lts')))

    def test_boot_config_preserves_root_and_lts(self):
        original = ('ESP_PATH="/boot"\n'
                    'KERNEL_CMDLINE[default]+="quiet rw root=UUID=ROOT_ID rootflags=subvol=/@"\n'
                    'KERNEL_CMDLINE[linux-cachyos-lts]="rw root=UUID=LTS_ROOT"\n')
        updated = config.transform(original)
        self.assertTrue(updated.startswith(original))
        self.assertIn('root=UUID=ROOT_ID rootflags=subvol=/@', updated)
        self.assertIn('ga107_unlock.ss1_full=1', updated)
        self.assertEqual(config.transform(updated), updated)
        self.assertEqual(updated.count('KERNEL_CMDLINE[linux-cachyos]='), 1)
        toggled = updated.replace('ga107_unlock.ss1_full=1', 'ga107_unlock.ss1_full=0')
        self.assertEqual(config.transform(toggled), updated)

    def test_boot_config_refuses_ambiguous_or_executable_input(self):
        for original in ['KERNEL_CMDLINE[default]="quiet"\n',
                         'KERNEL_CMDLINE[default]="rw root=$ROOT"\n',
                         'KERNEL_CMDLINE[default]="rw root=ROOT; echo bad"\n',
                         'KERNEL_CMDLINE[default]="rw root=ROOT acpi_osi=\\"Windows 2020\\""\n']:
            with self.assertRaises(ValueError):
                config.transform(original)

    def test_desktop_quote_and_validation(self):
        self.assertEqual(installer.exec_quote('/tmp/path with space/app.py'), '"/tmp/path with space/app.py"')
        self.assertIn('%%', installer.exec_quote('/tmp/a%b'))
        self.assertIn('--startup', installer.desktop_entry(True))
        self.assertNotIn('--startup', installer.desktop_entry(False))


if __name__ == '__main__':
    unittest.main()
