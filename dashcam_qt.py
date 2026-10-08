"""Qt desktop interface. Live captures, Transfer copies originals, Studio manages files."""
from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path

try:
    import PySide6
except ImportError:
    if __name__=='__main__' and os.name=='nt':
        import ctypes
        ctypes.windll.user32.MessageBoxW(None,'The Qt interface needs PySide6. Install the requirements listed in README.md using this Python installation, then reopen DashGo.','DashGo Desktop',0x10)
        raise SystemExit(1)
    raise

from PySide6.QtCore import Qt, QTimer, QSize, QUrl
from PySide6.QtGui import QImage, QPainter, QColor, QDesktopServices, QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QToolButton, QMenu, QTabWidget, QComboBox, QCheckBox, QProgressBar,
    QTreeWidget, QTreeWidgetItem, QHeaderView, QAbstractItemView, QDialog, QDialogButtonBox,
    QFormLayout, QLineEdit, QFileDialog, QDoubleSpinBox, QSpinBox, QMessageBox, QPlainTextEdit,
    QFrame, QSizePolicy)

from dashcam_desktop import Desktop, inventory
from dashcam_live import describe_probe
from dashcam_power import KeepAwake
from dashcam_recycle import plan_recycle, recycle_plan, checked_path, snapshot, recycle_windows
from dashcam_history import DownloadHistory
from dashcam_stitch import output_name


def human(value):
    for unit in ('B','KiB','MiB','GiB','TiB'):
        if value<1024 or unit=='TiB':return f'{value:.1f} {unit}'
        value/=1024


STYLE = '''
QMainWindow, QDialog { background: #f5f6f8; }
QWidget { color: #202a36; font-family: "Segoe UI"; font-size: 10pt; }
QLabel#brand { font-size: 17pt; font-weight: 600; }
QLabel#heading { font-size: 14pt; font-weight: 600; }
QLabel#muted { color: #596575; }
QTabWidget::pane { border: 0; background: #f5f6f8; }
QTabBar::tab { background: transparent; padding: 13px 28px; border-bottom: 2px solid transparent; color: #566274; }
QTabBar::tab:selected { color: #2159ad; border-bottom: 2px solid #2159ad; font-weight: 600; }
QTabBar::tab:hover { background: #e9edf3; }
QPushButton, QToolButton { background: #ffffff; border: 1px solid #c9d0da; border-radius: 6px; padding: 9px 15px; }
QPushButton:hover, QToolButton:hover { background: #eaf0f8; border-color: #92a8c7; }
QPushButton:pressed, QToolButton:pressed { background: #dce7f6; }
QPushButton:focus, QToolButton:focus, QComboBox:focus, QLineEdit:focus, QTreeWidget:focus { border: 2px solid #356ec0; }
QPushButton:disabled, QToolButton:disabled { color: #89929e; background: #edf0f4; border-color: #dbe0e7; }
QPushButton[primary="true"] { background: #245caa; color: white; border-color: #245caa; font-weight: 600; }
QPushButton[primary="true"]:hover { background: #194c95; }
QPushButton[primary="true"]:disabled { background: #d4dfed; color: #74849b; border-color: #d4dfed; }
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox { background: white; border: 1px solid #c9d0da; border-radius: 5px; padding: 7px 9px; min-height: 20px; }
QComboBox { min-width: 100px; padding-right: 26px; }
QComboBox QAbstractItemView { background: white; selection-background-color: #e0eafa; selection-color: #202a36; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #8999ad; border-radius: 3px; background: white; }
QCheckBox::indicator:checked { background: #245caa; border: 3px solid #c4d8f5; }
QCheckBox::indicator:disabled { border-color: #c9d0da; }
QTreeWidget { background: white; border: 1px solid #dbe0e7; border-radius: 7px; outline: 0; }
QTreeWidget::item { padding: 9px 6px; border-bottom: 1px solid #f0f2f5; }
QTreeWidget::item:selected { background: #e3edfb; color: #143d79; }
QTreeWidget::item:hover:!selected { background: #f5f8fc; }
QHeaderView::section { background: #edf1f6; color: #526071; border: 0; border-bottom: 1px solid #dbe0e7; padding: 10px 12px; font-weight: 600; }
QProgressBar { background: #e1e7ef; border: 0; border-radius: 3px; min-height: 6px; max-height: 6px; }
QProgressBar::chunk { background: #326bb8; border-radius: 3px; }
QPlainTextEdit { background: white; border: 1px solid #dbe0e7; font-family: Consolas; font-size: 9pt; }
QMenu { background: white; border: 1px solid #d3dbe5; padding: 5px; }
QMenu::item { padding: 8px 28px 8px 12px; }
QMenu::item:selected { background: #e3edfb; }
QToolTip { background: #202a36; color: white; border: none; padding: 6px; }
'''


class Viewport(QWidget):
    def __init__(self):
        super().__init__();self.image=QImage();self.setMinimumHeight(240)
        self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding)
        self.setAccessibleName('Live camera preview')

    def set_frame(self, data):
        image=QImage.fromData(data,'PPM')
        if not image.isNull():self.image=image;self.update()

    def paintEvent(self,event):
        painter=QPainter(self);painter.fillRect(self.rect(),QColor('#101722'))
        if self.image.isNull():
            painter.setPen(QColor('#a0acbd'));painter.drawText(self.rect(),Qt.AlignCenter,'Camera not connected')
        else:
            size=self.image.size().scaled(self.size(),Qt.KeepAspectRatio)
            size=QSize(min(size.width(),self.image.width()),min(size.height(),self.image.height()))
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.drawImage((self.width()-size.width())//2,(self.height()-size.height())//2,self.image.scaled(size,Qt.KeepAspectRatio,Qt.SmoothTransformation))


class Window(QMainWindow):
    def __init__(self,desktop=None):
        super().__init__()
        self.desktop=desktop or Desktop(auto_connect=os.environ.get('DASHGO_NO_AUTO_CONNECT')!='1')
        self.setWindowTitle('DashGo Desktop');self.resize(1120,820);self.setMinimumSize(960,700)
        self.setStyleSheet(STYLE);self.keep_awake=KeepAwake();self._closing=False
        self._log_count=0;self._last_tick=time.monotonic();self._last_notice='';self._selected_export=None
        shell=QWidget();self.setCentralWidget(shell);outer=QVBoxLayout(shell);outer.setContentsMargins(26,20,26,16);outer.setSpacing(15)
        top=QHBoxLayout();brand=QLabel('DashGo Desktop');brand.setObjectName('brand');top.addWidget(brand);top.addStretch()
        tools=self.menu_button('Tools',[('Logs',self.show_logs)]);top.addWidget(tools);outer.addLayout(top)
        self.tabs=QTabWidget();self.tabs.setDocumentMode(True);self.tabs.tabBar().setDrawBase(False);outer.addWidget(self.tabs,1)
        self.live_page,self.live_layout=self.page('Live')
        self.transfer_page,self.transfer_layout=self.page('Transfer')
        self.studio_page,self.studio_layout=self.page('Studio')
        self.build_live();self.build_transfer();self.build_studio()
        self.footer=QLabel('');self.footer.setObjectName('muted');outer.addWidget(self.footer)
        self.logs_dialog=QDialog(self);self.logs_dialog.setWindowTitle('Logs');self.logs_dialog.resize(900,580)
        layout=QVBoxLayout(self.logs_dialog);self.logs_view=QPlainTextEdit();self.logs_view.setReadOnly(True);self.logs_view.document().setMaximumBlockCount(2000);layout.addWidget(self.logs_view)
        controls=QHBoxLayout();controls.addStretch()
        controls.addWidget(self.button('Clear display',self.clear_logs))
        controls.addWidget(self.button('Open log file',self.open_log));layout.addLayout(controls)
        self.timer=QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(100)
        self.tabs.currentChanged.connect(lambda:self.refresh_library() if self.tabs.currentWidget()==self.studio_page else None)
        self.refresh_library();self.tick()

    def page(self,name):
        widget=QWidget();layout=QVBoxLayout(widget);layout.setContentsMargins(0,18,0,0);layout.setSpacing(16);self.tabs.addTab(widget,name);return widget,layout

    def label(self,text='',muted=False):
        label=QLabel(text);label.setWordWrap(True)
        if muted:label.setObjectName('muted')
        return label

    def button(self,text,callback,primary=False):
        button=QPushButton(text);button.setProperty('primary',primary);button.clicked.connect(lambda:self.action(callback));return button

    def menu_button(self,text,items):
        button=QToolButton();button.setText(text);button.setPopupMode(QToolButton.InstantPopup);menu=QMenu(button)
        for label,callback in items:
            if label is None:menu.addSeparator();continue
            action=menu.addAction(label);action.triggered.connect(lambda checked=False,fn=callback:self.action(fn))
        button.setMenu(menu);return button

    def action(self,callback):
        try:callback()
        except Exception as exc:
            self.desktop.log(str(exc));QMessageBox.warning(self,'DashGo Desktop',str(exc))
        self.update_controls()

    def build_live(self):
        row=QHBoxLayout();self.connection_label=self.label('Camera not connected');row.addWidget(self.connection_label,1)
        self.live_options=self.menu_button('Options',[
            ('Reconnect',lambda:self.desktop.connect()),('Live settings',lambda:self.settings('live')),
            ('Cancel connection',self.desktop.cancel_connection)])
        row.addWidget(self.live_options);self.live_layout.addLayout(row)
        self.viewport=Viewport();self.live_layout.addWidget(self.viewport,1)
        actions=QHBoxLayout();self.capture_button=self.button('Start Capture',self.toggle_capture,True);actions.addWidget(self.capture_button)
        actions.addSpacing(14);actions.addWidget(QLabel('Capture quality'))
        self.capture_quality=QComboBox()
        for text,value in [('720p · source',720),('480p',480),('360p',360)]:self.capture_quality.addItem(text,value)
        self.capture_quality.currentIndexChanged.connect(lambda:self.set_option('capture_quality',self.capture_quality.currentData()))
        actions.addWidget(self.capture_quality);actions.addStretch()
        self.render_option=QCheckBox('Background render with music');self.render_option.setChecked(self.desktop.render_enabled)
        self.render_option.toggled.connect(lambda value:self.set_option('render_enabled',value));actions.addWidget(self.render_option)
        self.live_layout.addLayout(actions)
        self.live_detail=self.label('',True);self.live_layout.addWidget(self.live_detail)

    def build_transfer(self):
        header=QHBoxLayout();title=QLabel('Camera storage');title.setObjectName('heading');header.addWidget(title);header.addStretch()
        header.addWidget(self.menu_button('Options',[('Transfer settings',lambda:self.settings('transfer')),
            ('Scan stored clips',lambda:self.desktop.transfer(scan=True)),('Open transfer folder',lambda:self.open_path(self.desktop.transfer_dir))]))
        self.transfer_layout.addLayout(header)
        self.transfer_layout.addWidget(self.label('Copies original front-camera clips from the SD card without re-encoding.',True))
        self.transfer_layout.addSpacing(10)
        self.transfer_button=self.button('Transfer clips',self.toggle_transfer,True)
        row=QHBoxLayout();row.addWidget(self.transfer_button);row.addStretch();self.transfer_layout.addLayout(row)
        self.transfer_progress=QProgressBar();self.transfer_progress.setTextVisible(False);self.transfer_layout.addWidget(self.transfer_progress)
        self.transfer_detail=self.label();self.transfer_layout.addWidget(self.transfer_detail)
        self.transfer_history=self.label('',True);self.transfer_layout.addWidget(self.transfer_history)
        self.transfer_layout.addStretch()
        self.transfer_folder=self.label('',True);self.transfer_folder.setTextInteractionFlags(Qt.TextSelectableByMouse);self.transfer_layout.addWidget(self.transfer_folder)

    def build_studio(self):
        top=QHBoxLayout();top.addWidget(QLabel('Output size target'))
        self.output_target=QComboBox()
        for label,value in [('1 GB / hour','1gbh'),('2 GB / hour','2gbh'),('4 GB / hour','4gbh'),('8 GB / hour','8gbh'),('Source quality','original')]:self.output_target.addItem(label,value)
        self.output_target.setCurrentIndex(self.output_target.findData(self.desktop.target));self.output_target.currentIndexChanged.connect(lambda:self.set_option('target',self.output_target.currentData()))
        top.addWidget(self.output_target);top.addStretch()
        self.studio_options=self.menu_button('Options',[
            ('Studio settings',lambda:self.settings('studio')),('Refresh files',self.refresh_library),
            ('Stop background rendering',self.stop_render),(None,None),('Delete selected files…',self.delete_selected)])
        top.addWidget(self.studio_options);self.studio_layout.addLayout(top)
        self.library=QTreeWidget();self.library.setHeaderLabels(['Name','Type','Status','Size']);self.library.setUniformRowHeights(True)
        self.library.setSelectionMode(QAbstractItemView.ExtendedSelection);self.library.setRootIsDecorated(True)
        self.library.header().setSectionResizeMode(0,QHeaderView.Stretch)
        for index,width in ((1,150),(2,160),(3,110)):self.library.header().resizeSection(index,width)
        self.library.setAccessibleName('Capture and transferred-drive files');self.library.itemSelectionChanged.connect(self.selection_changed)
        self.library.itemDoubleClicked.connect(lambda item,column:self.open_selected())
        self.studio_layout.addWidget(self.library,1)
        self.empty=self.label('No captures or transferred clips yet.',True);self.studio_layout.addWidget(self.empty)
        bar=QHBoxLayout();self.selection_detail=self.label('Select a capture or drive to export.',True);bar.addWidget(self.selection_detail,1)
        self.open_button=self.button('Open folder',self.open_selected);bar.addWidget(self.open_button)
        self.export_button=self.button('Export Final',self.export_selected,True);bar.addWidget(self.export_button)
        self.studio_layout.addLayout(bar)
        self.export_progress=QProgressBar();self.export_progress.setTextVisible(False);self.studio_layout.addWidget(self.export_progress)
        self.studio_detail=self.label();self.studio_layout.addWidget(self.studio_detail)
        delete=QAction(self);delete.setShortcut(QKeySequence.Delete);delete.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        delete.triggered.connect(lambda:self.action(self.delete_selected));self.library.addAction(delete)

    def set_option(self,name,value):
        setattr(self.desktop,name,value)

    def toggle_capture(self):
        if self.desktop.operation=='capture_start' or self.desktop.capture and self.desktop.capture.active:self.desktop.stop_capture()
        else:self.desktop.start_capture()

    def toggle_transfer(self):
        if self.desktop.operation=='transfer':self.desktop.cancel_command()
        else:self.desktop.transfer()

    def stop_render(self):
        if self.desktop.renderer:self.desktop.renderer.stop()

    def selected(self):
        return [item.data(0,Qt.UserRole) for item in self.library.selectedItems()]

    def selection_changed(self):
        rows=self.selected();size=sum(row['size'] for row in rows)
        self.selection_detail.setText(f'{len(rows)} selected · {human(size)}' if rows else 'Select a capture or drive to export.')
        self.update_controls()

    def refresh_library(self):
        def identity(row):return (str(row['path']),row['kind'],row['drive'][0].started if row.get('drive') else None)
        selected={identity(row) for row in self.selected()} if hasattr(self,'library') else set()
        try:rows=inventory(self.desktop)
        except (OSError,ValueError) as exc:self.desktop.log('Inventory: '+str(exc));return
        self.library.blockSignals(True);self.library.clear()
        def add(parent,row):
            item=QTreeWidgetItem(parent,[row['name'],row['kind'],row['status'],human(row['size'])]);item.setData(0,Qt.UserRole,row)
            item.setToolTip(0,str(row['path']));item.setSelected(identity(row) in selected)
            for child in row['children']:add(item,child)
        for row in rows:add(self.library,row)
        if self.desktop.last_export and self.desktop.last_export!=self._selected_export:
            for index in range(self.library.topLevelItemCount()):
                item=self.library.topLevelItem(index)
                if item.data(0,Qt.UserRole)['path']==self.desktop.last_export:
                    self.library.clearSelection();item.setSelected(True);self.library.scrollToItem(item)
                    self._selected_export=self.desktop.last_export;break
        self.library.blockSignals(False);self.empty.setVisible(not rows);self.selection_changed();self.desktop.refresh_needed=False
        self.transfer_folder.setText('Transfer folder: '+str(self.desktop.transfer_dir))
        history=self.desktop.transfer_dir/'.dashcam_history.sqlite3'
        if history.exists():
            try:
                with DownloadHistory(history) as db:total,present,missing=db.stats()
                self.transfer_history.setText(f'{total} clips in download history · {present} local · {missing} removed or missing')
            except Exception as exc:self.transfer_history.setText('History unavailable: '+str(exc))
        else:self.transfer_history.setText('No download history yet.')

    def export_selected(self):
        d=self.desktop
        if d.finalizer or d.pending_export or d.operation=='studio':d.cancel_export();return
        rows=self.selected()
        if not rows:raise ValueError('Select a capture or transferred drive first.')
        captures={r['session'] for r in rows if r.get('session') and r['kind'] in ('Capture','Raw segment','Rendered segment')}
        if captures:
            if len(captures)!=1 or any(r['kind'] not in ('Capture','Raw segment','Rendered segment') for r in rows):raise ValueError('Select one capture at a time.')
            d.export_capture(next(iter(captures)));return
        drives=[r['drive'] for r in rows if r.get('drive')]
        if len(drives)!=len(rows):raise ValueError('Select a capture or a transferred-drive row. This file is already an output.')
        # Transferred-drive rendering has always supported explicit replacement.
        existing=[]
        for drive in drives:
            output=d.transfer_dir/'Drives'/output_name(drive,d.target)
            existing.extend(p for p in (output,output.with_name(output.name+'.part.mp4')) if p.exists())
        if existing:
            if QMessageBox.question(self,'Replace drive exports?','Replace these matching exports or partial renders? Source clips remain.\n\n'+'\n'.join(str(p) for p in existing),QMessageBox.Yes|QMessageBox.Cancel,QMessageBox.Cancel)!=QMessageBox.Yes:return
        d.render_drives(drives)

    def open_path(self,path):
        path=Path(path)
        if not path.exists():raise ValueError('This folder does not exist yet.')
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path if path.is_dir() else path.parent)))

    def open_selected(self):
        rows=self.selected()
        if rows:self.open_path(rows[0]['path'])

    def delete_selected(self):
        d=self.desktop
        if d.media_busy:raise RuntimeError('Finish capture, transfer, rendering and export before deleting files.')
        rows=self.selected()
        if not rows:raise ValueError('Select the files to delete first.')
        capture_paths=[];other=[]
        for row in rows:
            if row.get('session'):capture_paths.append(row['path'])
            elif row.get('drive'):other.extend(c['path'] for c in row['children'])
            else:other.append(row['path'])
        capture_items=plan_recycle(d.capture_dir,capture_paths) if capture_paths else ()
        other_files={}
        if other:
            root=checked_path(d.transfer_dir)
            for path in set(other):
                path=checked_path(path)
                if not path.is_file() or not path.is_relative_to(root):raise ValueError('Selected file is outside the transfer folder.')
                relative=path.relative_to(root)
                if not ((len(relative.parts)==1 and path.name.endswith('_f.ts')) or (len(relative.parts)==2 and relative.parts[0]=='Drives' and (path.name.endswith('.mp4') or '.mp4.part' in path.name))):raise ValueError('This is not a listed transfer media file.')
                other_files[path]=snapshot(path)
        scopes=[(item.kind,item.path,item.file_count,item.size) for item in capture_items]+[('Selected file',p,1,p.stat().st_size) for p in other_files]
        if not self.confirm_delete(scopes):return
        def busy():return bool(d.closed or d.operation not in ('','recycle') or d.pending_export or d.process or any(j and j.active for j in (d.capture,d.renderer,d.finalizer)))
        if busy():raise RuntimeError('A media job started; no files were changed.')
        def run():
            moved,failures=recycle_plan(d.capture_dir,capture_items,is_busy=busy) if capture_items else ([],[])
            for path,stamp in other_files.items():
                if failures:break
                def validate(path=path,stamp=stamp):
                    if busy() or snapshot(path)!=stamp:raise ValueError('Selection or job state changed; remaining files were kept.')
                try:
                    validate();recycle_windows(path,validate)
                    if path.exists():raise OSError('Windows did not recycle this file.')
                    moved.append(path)
                    if path.name.endswith('_f.ts'):
                        with DownloadHistory(d.transfer_dir/'.dashcam_history.sqlite3') as history:history.mark_present_by_filename(path.name,False)
                except Exception as exc:failures.append((path,str(exc)))
            if failures:raise RuntimeError(f'{len(moved)} items recycled; remaining files kept. '+failures[0][1])
            return f'{len(moved)} items moved to the Recycle Bin.'
        d._worker('recycle',run);d.studio_status='Moving selected files to the Recycle Bin.'

    def confirm_delete(self,scopes):
        dialog=QDialog(self);dialog.setWindowTitle('Move selected files to the Recycle Bin?');dialog.resize(860,460)
        layout=QVBoxLayout(dialog);layout.addWidget(self.label('Review the exact scope below. Whole capture folders include all their contents; separate final exports require their own selection.'))
        table=QTreeWidget();table.setHeaderLabels(['Scope','Path','Files','Size']);table.setRootIsDecorated(False)
        table.header().setSectionResizeMode(1,QHeaderView.Stretch)
        for kind,path,count,size in scopes:
            item=QTreeWidgetItem(table,[kind,str(path),str(count),human(size)]);item.setToolTip(1,str(path))
        layout.addWidget(table)
        layout.addWidget(self.label('Removing working segments can prevent another export. Camera files and original music are unchanged. No permanent deletion fallback.',True))
        buttons=QDialogButtonBox(QDialogButtonBox.Cancel);confirm=buttons.addButton('Move to Recycle Bin',QDialogButtonBox.AcceptRole)
        confirm.setAutoDefault(False);buttons.button(QDialogButtonBox.Cancel).setDefault(True);buttons.button(QDialogButtonBox.Cancel).setFocus()
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        return dialog.exec()==QDialog.Accepted

    def settings(self,kind):
        d=self.desktop;dialog=QDialog(self);dialog.setWindowTitle(kind.title()+' settings');dialog.resize(740,430)
        layout=QVBoxLayout(dialog);form=QFormLayout();form.setVerticalSpacing(13);layout.addLayout(form);fields={}
        def text(name,label,path=False):
            editor=QLineEdit(str(getattr(d,name)));editor.setAccessibleName(label)
            if path:
                row=QHBoxLayout();row.addWidget(editor);browse=QPushButton('Browse');row.addWidget(browse)
                def choose():
                    result=QFileDialog.getExistingDirectory(dialog,label,editor.text())
                    if result:editor.setText(result)
                browse.clicked.connect(choose);form.addRow(label,row)
            else:form.addRow(label,editor)
            fields[name]=(editor,Path if path else str)
        def number(name,label,minimum,maximum,integer=False):
            editor=QSpinBox() if integer else QDoubleSpinBox();editor.setRange(minimum,maximum);editor.setValue(getattr(d,name));form.addRow(label,editor);fields[name]=(editor,int if integer else float)
        if kind=='live':
            text('camera','Camera address');text('stream','Live stream URL');text('capture_dir','Capture folder',True)
            if d.candidates:
                cameras=QComboBox()
                for item in d.candidates:cameras.addItem(item['address'])
                form.addRow('Detected cameras',cameras);cameras.currentTextChanged.connect(fields['camera'][0].setText)
                fields['camera'][0].setText(cameras.currentText())
            details=self.label(describe_probe(d.report) if d.report else 'Stream has not been measured.',True);layout.addWidget(details)
            if d.capabilities:
                layout.addWidget(self.label('Device: '+str(d.capabilities.get('firmware','Unknown'))+' · '+str(d.capabilities.get('cameras','Unknown'))+' camera(s)',True))
                values={v.get('name'):v.get('value') for v in d.capabilities.get('values',[]) if isinstance(v,dict)}
                table=QTreeWidget();table.setHeaderLabels(['Camera setting (read-only)','Current value']);table.setRootIsDecorated(False)
                allowed={'mic','rec','switchcam','osd','rec_resolution','rec_split_duration','key_tone','speaker','gsr_sensitivity','light_fre','screen_standby'}
                names={'mic':'Microphone','rec':'SD recording','switchcam':'Camera selection','osd':'Camera date overlay','rec_resolution':'SD recording resolution','rec_split_duration':'SD clip length','key_tone':'Button sound','speaker':'Speaker','gsr_sensitivity':'G-sensor sensitivity','light_fre':'Light frequency','screen_standby':'Camera screen standby'}
                for item in d.capabilities.get('items',[]):
                    if isinstance(item,dict) and item.get('name') in allowed:
                        choices=dict(zip(item.get('index',[]),item.get('items',[])));QTreeWidgetItem(table,[names[item['name']],str(choices.get(values.get(item['name']),'Unknown'))])
                layout.addWidget(table)
            actions=QHBoxLayout()
            for title,fn in [('Connect address',lambda:d.connect(fields['camera'][0].text().strip())),('Read device info',lambda:d.identify(fields['camera'][0].text().strip())),('Measure stream',lambda:d.measure(fields['stream'][0].text().strip()))]:
                def dispatch(fn=fn):
                    fn();dialog.reject()
                button=self.button(title,dispatch);button.setEnabled(not d.media_busy);actions.addWidget(button)
            layout.addLayout(actions)
        elif kind=='transfer':
            text('camera','Camera address (blank = discover)');text('transfer_dir','Transfer folder',True)
            number('skip_newest','Skip newest clips',0,100,True)
            check=QCheckBox('Re-download sources removed locally');check.setChecked(d.redownload);form.addRow(check);fields['redownload']=(check,bool)
            layout.addWidget(self.label('Download history is retained when local files are removed. Original source resolution is preserved.',True))
        else:
            text('music_dir','Music folder',True);text('channel_title','Channel title');text('route_info','Route information')
            number('crossfade','Crossfade (seconds)',.1,60);number('end_card','End card (seconds)',.1,120);number('gap_minutes','New drive after gap (minutes)',.1,120)
            encoder=QComboBox();encoder.addItems(['auto','h264_nvenc','libx264']);encoder.setCurrentText(d.video_encoder);form.addRow('Video encoder',encoder);fields['video_encoder']=(encoder,str)
            layout.addWidget(self.label('Live background rendering uses CPU H.264 and an ending up to 20 seconds. Encoder and end-card settings here apply to transferred drives.',True))
        layout.addStretch();buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);layout.addWidget(buttons)
        buttons.rejected.connect(dialog.reject);buttons.accepted.connect(dialog.accept)
        if dialog.exec()!=QDialog.Accepted:return
        if d.media_busy:raise RuntimeError('Finish the current task before changing settings.')
        previous_stream=d.stream
        updates={}
        for name,(editor,convert) in fields.items():
            value=editor.isChecked() if isinstance(editor,QCheckBox) else editor.value() if isinstance(editor,(QSpinBox,QDoubleSpinBox)) else editor.currentText() if isinstance(editor,QComboBox) else editor.text().strip()
            if convert is Path and not value:raise ValueError('Choose a nonempty folder path.')
            updates[name]=convert(value)
        for name,value in updates.items():setattr(d,name,value)
        if previous_stream!=d.stream:d.report=None
        self.refresh_library()

    def show_logs(self):
        self.logs_view.setPlainText('\n'.join(self.desktop.logs));self.logs_dialog.show();self.logs_dialog.raise_()

    def clear_logs(self):
        self.desktop.logs.clear();self.logs_view.clear();self._log_count=0

    def open_log(self):
        path=self.desktop.transfer_dir/'dashcam_transfer.log'
        if not path.is_file():raise ValueError('No log file yet.')
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def update_controls(self):
        d=self.desktop;capturing=bool(d.operation=='capture_start' or d.capture and d.capture.active);exporting=bool(d.finalizer or d.pending_export or d.operation=='studio')
        self.capture_button.setText('Stop Capture' if capturing else 'Start Capture')
        self.capture_button.setEnabled(capturing or bool(d.report and not d.media_busy))
        self.capture_quality.setEnabled(not d.media_busy);self.render_option.setEnabled(not d.media_busy)
        self.output_target.setEnabled(not exporting and d.operation not in ('capture_start','studio'))
        self.transfer_button.setText('Cancel transfer' if d.operation=='transfer' else 'Transfer clips')
        self.transfer_button.setEnabled(d.operation=='transfer' or not d.media_busy)
        self.export_button.setText('Cancel export' if exporting else 'Export Final')
        rows=self.selected()
        exportable=bool(rows) and all(r['kind'] in ('Capture','Raw segment','Rendered segment','Transferred drive') for r in rows)
        can_queue=bool(d.renderer and d.renderer.active and not capturing and not d.operation)
        self.export_button.setEnabled(exporting or exportable and (not d.media_busy or can_queue))
        self.open_button.setEnabled(bool(rows))
        self.transfer_progress.setVisible(d.operation=='transfer' or d.transfer_percent>0)
        self.export_progress.setVisible(exporting)

    def tick(self):
        try:
            now=time.monotonic();delay=now-self._last_tick;self._last_tick=now
            if delay>1:self.desktop.log(f'UI update delayed {delay:.2f}s')
            self.desktop.poll();d=self.desktop
            frame=d.frame()
            if frame:self.viewport.set_frame(frame)
            elif not d.preview and not(d.capture and d.capture.active):self.viewport.image=QImage();self.viewport.update()
            self.connection_label.setText(d.live_status)
            self.live_detail.setText((describe_probe(d.report)+'\n' if d.report else '')+'Capture folder: '+str(d.capture_dir))
            self.transfer_detail.setText(d.transfer_status);self.transfer_progress.setValue(round(d.transfer_percent))
            self.studio_detail.setText(d.studio_status if len(d.studio_status)<=260 else d.studio_status[:225]+'… See Tools > Logs.');self.studio_detail.setToolTip(d.studio_status)
            if d.operation=='studio':self.export_progress.setRange(0,0)
            else:self.export_progress.setRange(0,100);self.export_progress.setValue(round(d.export_percent))
            self.keep_awake.update(d.awake_reasons)
            self.footer.setText('Keeping PC awake during media jobs' if self.keep_awake.active else '')
            if d.refresh_needed:self.refresh_library()
            if self.logs_dialog.isVisible() and self._log_count!=len(d.logs):self.logs_view.setPlainText('\n'.join(d.logs));self._log_count=len(d.logs)
            self.update_controls()
        except Exception as exc:
            text=str(exc)
            if text!=self._last_notice:self.desktop.log('Interface: '+text);self._last_notice=text
            self.footer.setText(text)

    def closeEvent(self,event):
        if not self._closing and self.desktop.media_busy:
            if QMessageBox.question(self,'Close DashGo?','Stop the current capture, rendering, transfer or export and close?',QMessageBox.Yes|QMessageBox.Cancel,QMessageBox.Cancel)!=QMessageBox.Yes:event.ignore();return
        self._closing=True
        try:self.desktop.close()
        except TimeoutError:
            event.ignore();self.footer.setText('Waiting for the current task to stop.');QTimer.singleShot(300,self.close);return
        self.timer.stop();self.keep_awake.close();event.accept()


def main():
    app=QApplication(sys.argv);app.setStyle('Fusion');app.setPalette(app.style().standardPalette());app.setApplicationName('DashGo Desktop')
    window=Window();window.show();return app.exec()


if __name__=='__main__':sys.exit(main())
