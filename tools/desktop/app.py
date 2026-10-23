#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Desktop status window with an explicitly started register MMA benchmark."""
import argparse
import json
import os
from pathlib import Path
import sys

from status import ROOT, collect, repair_commands, save_summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--startup', action='store_true', help='After login, only show a window if action is needed')
    parser.add_argument('--check', action='store_true', help='Print a privacy-filtered summary without opening the UI')
    args = parser.parse_args()
    if args.check:
        s = collect()
        print(json.dumps({k: s[k] for k in ('kernel', 'source_version', 'loaded_version', 'installed_version',
            'state', 'applied', 'execute', 'ss1_full', 'reasons')}, ensure_ascii=False, indent=2))
        return
    try:
        from PySide6.QtCore import QThread, Signal, QTimer, Qt, QProcess
        from PySide6.QtGui import QFontDatabase
        from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
            QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QFormLayout, QTabWidget)
    except ImportError:
        raise SystemExit('PySide6가 필요합니다. CachyOS: sudo pacman -S --needed pyside6')

    class Worker(QThread):
        done = Signal(object)

        def run(self):
            try:
                self.done.emit(collect())
            except Exception as error:
                self.done.emit({'error': type(error).__name__ + ': ' + str(error)})

    class Window(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle('GA107 언락 확인')
            self.resize(940, 730)
            self.worker = None
            self.first = True
            self.quit_when_done = False
            self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(24, 20, 24, 20)
            self.heading = QLabel('현재 부팅을 확인하고 있습니다…')
            self.heading.setStyleSheet('font-size: 23px; font-weight: 600;')
            layout.addWidget(self.heading)
            self.description = QLabel('커널·모듈·SS0/SS1 완료 로그와 NVIDIA 응답을 조회합니다.')
            self.description.setWordWrap(True)
            layout.addWidget(self.description)
            self.form = QFormLayout()
            self.fields = {}
            for key, label in [('kernel','현재 커널'), ('source_version','소스 버전'),
                    ('installed_version','디스크 모듈'), ('loaded_version','현재 로드된 모듈'),
                    ('options','실행 옵션'), ('driver','NVIDIA 상태')]:
                value = QLabel('확인 중')
                value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                self.form.addRow(label, value)
                self.fields[key] = value
            layout.addLayout(self.form)
            self.note = QLabel('자동으로 빌드·설치·GPU 쓰기·재부팅을 실행하지 않습니다.')
            self.note.setWordWrap(True)
            layout.addWidget(self.note)
            tabs = self.tabs = QTabWidget()
            self.commands, self.evidence = QPlainTextEdit(), QPlainTextEdit()
            self.benchmark_output = QPlainTextEdit()
            self.benchmark_output.setPlainText('실행 버튼을 누르면 FP16·BF16·TF32·INT8 레지스터 MMA를 측정합니다.\n'
                '메모리 대역폭 테스트는 실행하지 않습니다. 결과는 이 창에만 표시합니다.\n'
                '클럭·전력 설정을 변경하거나 언락 여부를 판정하지 않습니다.\n'
                'CUDA Toolkit(nvcc)이 필요하며, 첫 실행에는 컴파일 시간이 걸립니다.')
            for editor in (self.commands, self.evidence, self.benchmark_output):
                editor.setReadOnly(True)
                editor.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
                editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
            tabs.addTab(self.commands, '적용 명령어')
            tabs.addTab(self.evidence, '현재 부팅 근거')
            tabs.addTab(self.benchmark_output, '성능 벤치마크')
            self.benchmark_process = QProcess(self)
            self.benchmark_process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
            self.benchmark_process.readyReadStandardOutput.connect(self.read_benchmark)
            self.benchmark_process.finished.connect(self.benchmark_finished)
            self.benchmark_process.errorOccurred.connect(self.benchmark_error)
            layout.addWidget(tabs, 1)
            buttons = QHBoxLayout()
            self.refresh = QPushButton('다시 검사')
            self.refresh.clicked.connect(self.check)
            self.benchmark_button = QPushButton('레지스터 MMA 실행')
            self.benchmark_button.clicked.connect(self.run_benchmark)
            self.copy = QPushButton('명령어 전체 복사')
            self.copy.clicked.connect(lambda: QApplication.clipboard().setText(self.commands.toPlainText()))
            close = QPushButton('닫기')
            close.clicked.connect(self.close)
            buttons.addWidget(self.refresh)
            buttons.addWidget(self.benchmark_button)
            buttons.addStretch()
            buttons.addWidget(self.copy)
            buttons.addWidget(close)
            layout.addLayout(buttons)
            self.setCentralWidget(page)

        def run_benchmark(self):
            if self.benchmark_process.state() != QProcess.ProcessState.NotRunning:
                return
            self.tabs.setCurrentWidget(self.benchmark_output)
            self.benchmark_output.clear()
            self.benchmark_button.setEnabled(False)
            self.benchmark_process.setWorkingDirectory(str(ROOT))
            self.benchmark_process.start(sys.executable,
                ['-u', str(Path(__file__).with_name('benchmark.py'))])

        def read_benchmark(self):
            text = bytes(self.benchmark_process.readAllStandardOutput()).decode('utf-8', errors='replace')
            cursor = self.benchmark_output.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            cursor.insertText(text)
            self.benchmark_output.setTextCursor(cursor)
            self.benchmark_output.ensureCursorVisible()

        def benchmark_finished(self, code, exit_status):
            self.read_benchmark()
            self.benchmark_button.setEnabled(True)
            if code or exit_status == QProcess.ExitStatus.CrashExit:
                self.benchmark_output.appendPlainText(f'\n벤치마크가 완료되지 않았습니다 (종료 코드 {code}).')

        def benchmark_error(self, error):
            if error == QProcess.ProcessError.FailedToStart:
                self.benchmark_button.setEnabled(True)
                self.benchmark_output.appendPlainText(self.benchmark_process.errorString())

        def check(self):
            if self.worker is not None and self.worker.isRunning():
                return
            self.refresh.setEnabled(False)
            self.copy.setEnabled(False)
            self.heading.setText('현재 부팅을 확인하고 있습니다…')
            self.worker = Worker(self)
            self.worker.done.connect(self.update_status)
            self.worker.finished.connect(self.finished_check)
            self.worker.start()

        def finished_check(self):
            self.refresh.setEnabled(True)
            if self.quit_when_done:
                QApplication.instance().quit()

        def update_status(self, s):
            if 'error' in s:
                self.heading.setText('검사 중 오류가 발생했습니다')
                self.description.setText(s['error'])
                self.show()
                return
            cache = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache'))
            try:
                save_summary(s, cache / 'ga107-unlock-check/status.json')
            except OSError:
                pass
            for key in ('kernel','source_version','installed_version','loaded_version'):
                self.fields[key].setText(s[key] or '없음')
            self.fields['options'].setText(f"execute={s['execute'] or '없음'}, ss1_full={s['ss1_full'] or '없음'}")
            self.fields['driver'].setText(s['driver'] if s['driver_ok'] else '정상 응답 없음')
            self.description.setText('\n'.join(s['reasons']))
            self.evidence.setPlainText(s['evidence'] or '읽을 수 있는 적용 로그가 없습니다.')
            fully_current = (s['applied'] and s['installed_version'] == s['source_version']
                and s['loaded_version'] == s['source_version'] and not s['missing_firmware']
                and s['vermagic'].split()[:1] == [s['kernel']])
            if fully_current:
                self.heading.setText('SS0 · SS1 적용 확인')
                self.heading.setStyleSheet('font-size: 23px; font-weight: 600; color: #279568;')
                self.commands.setPlainText('현재 커널의 이번 부팅에서 SS0·SS1=8 적용을 확인했습니다.\n빌드·설치 명령을 실행할 필요가 없습니다.')
                self.copy.setEnabled(False)
                self.note.setText('이는 적용 로그와 드라이버 상태 검사입니다. 연산 성능은 벤치마크로 별도 확인합니다.')
            else:
                titles = {'applied':'적용 확인 · 설치 파일 점검 필요', 'inactive':'언락 적용을 확인하지 못했습니다',
                          'unknown':'로그 접근 등으로 확인할 수 없습니다', 'unsupported':'지원 대상 장치가 아닙니다'}
                self.heading.setText(titles[s['state']])
                self.heading.setStyleSheet('font-size: 23px; font-weight: 600; color: #d19136;')
                self.commands.setPlainText(repair_commands(s))
                self.copy.setEnabled(s['state'] != 'unsupported')
                self.note.setText('전체 복사 → 터미널에 붙여넣기. 오류가 나면 중단합니다. 완료 후 작업을 저장하고 완전히 종료했다가 켜세요. 현재 부팅에서 모듈을 재실행하지 않습니다.')
            if args.startup and self.first and fully_current:
                self.quit_when_done = True
            else:
                self.show()
            self.first = False

        def closeEvent(self, event):
            if self.benchmark_process.state() != QProcess.ProcessState.NotRunning:
                self.benchmark_output.appendPlainText('측정이 진행 중입니다. 완료 후 창을 닫을 수 있습니다.')
                self.tabs.setCurrentWidget(self.benchmark_output)
                event.ignore()
                return
            if self.worker is not None and self.worker.isRunning():
                self.hide()
                self.quit_when_done = True
                event.ignore()
            else:
                event.accept()

    app = QApplication(sys.argv[:1])
    app.setApplicationName('ga107-unlock-check')
    app.setDesktopFileName('ga107-unlock-check')
    app.setQuitOnLastWindowClosed(True)
    window = Window()
    if args.startup:
        QTimer.singleShot(12000, window.check)
    else:
        window.show()
        QTimer.singleShot(0, window.check)
    result = app.exec()
    # Destroy the widget/thread tree before QApplication. In particular, the
    # hidden autostart window must not survive into PySide interpreter cleanup.
    if window.worker is not None:
        window.worker.wait()
    import shiboken6
    shiboken6.delete(window)
    shiboken6.delete(app)
    return result


if __name__ == '__main__':
    main()
