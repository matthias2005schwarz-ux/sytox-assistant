"""Desktop orchestration contracts tested without Windows or screen access."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from sytox.actions import Toolkit, tool_schema
from sytox.agent import Agent
from sytox.storage import Store
from sytox.pc_control import DesktopUnavailable, WindowsDesktop


class FakeDesktop:
    def __init__(self):
        self.entry={'id': 1200, 'title':'Editor – privat', 'rect': [10, 20, 600, 480], 'active':False}
        self.active=None
        self.typed=[]
        self.clicked=[]
        self.combos=[]
        self.controls_clicked=[]
        self.controls={1:object()}

    def find_apps(self,query):
        return [{'name':'Editor','path':'C:/Editor.lnk'}] if query.casefold()=='editor' else []

    def windows(self):
        return [self.entry]

    def window(self, hwnd):
        if int(hwnd)!=1200:
            raise LookupError('Fenster existiert nicht')
        return dict(self.entry)

    def activate(self, hwnd):
        self.window(hwnd)
        self.active=int(hwnd)
        return self.entry

    def foreground_id(self):
        return self.active

    def inspect(self, hwnd):
        self.window(hwnd)
        return ([{'id':1,'name':'Speichern','type':'Button','rect':[100,200,200,230]}],
                self.controls.copy())

    def click_control(self, obj):
        self.controls_clicked.append(obj)

    def type_unicode(self, text, callback):
        callback()
        self.typed.append(text)

    def hotkey(self, keys):
        self.combos.append(keys)

    def click(self, x, y):
        self.clicked.append((x,y))


class TestDesktop(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'data.sqlite3')
        self.chat=self.store.create_chat()
        self.grants=[]
        def approve(label, detail):
            self.grants.append((label, detail))
            return True
        self.tool=Toolkit(self.store,Path(self.tmp.name)/'project',approve,threading.Event(),self.chat)
        self.tool.pc=FakeDesktop()
        self.addCleanup(self.tool.close)

    def select(self):
        return self.tool.call('pc_select_window',{'window_id':1200})

    def test_select_window_alone_is_not_proof_of_task_completion(self):
        self.store.add_message(self.chat,'user','Trage im Editor den Text Hallo ein')
        desktop=FakeDesktop()
        def tool_reply(name,**args):
            return {'role':'assistant','content':'','tool_calls':[
                {'function':{'name':name,'arguments':args}}]}
        agent=Agent(self.store,'test','http://invalid',str(Path(self.tmp.name)/'project'),
                    lambda *args:True,lambda *args:None,threading.Event())
        agent.client.chat=MagicMock(side_effect=[
            tool_reply('pc_select_window',window_id=1200),
            tool_reply('complete_task',summary='fertig',evidence='Fenster ausgewählt'),
            tool_reply('report_blocker',reason='Aktion noch nicht ausgeführt')])
        with patch('sytox.actions.WindowsDesktop',return_value=desktop):
            result=agent.run(self.chat,'until_done')
        self.assertEqual(result['status'],'paused')
        self.assertEqual(desktop.typed,[])

    def test_agent_controls_selected_window_end_to_end_with_fake_desktop(self):
        self.store.add_message(self.chat,'user','Schreibe bitte Hallo in das Editorfenster')
        desktop=FakeDesktop()
        def tool_reply(name,**args):
            return {'role':'assistant','content':'','tool_calls':[
                {'function':{'name':name,'arguments':args}}]}
        agent=Agent(self.store,'test','http://invalid',str(Path(self.tmp.name)/'project'),
                    lambda *args:True,lambda *args:None,threading.Event())
        agent.client.chat=MagicMock(side_effect=[
            tool_reply('pc_list_windows'),
            tool_reply('pc_select_window',window_id=1200),
            tool_reply('pc_type_text',text='Hallo aus SYTOX'),
            tool_reply('complete_task',summary='Text geschrieben',evidence='pc_type_text bestätigt')])
        with patch('sytox.actions.WindowsDesktop',return_value=desktop):
            result=agent.run(self.chat,'until_done')
        self.assertEqual(result['status'],'done')
        self.assertEqual(desktop.typed,['Hallo aus SYTOX'])
        self.assertEqual(agent.client.chat.call_count,4)

    def test_find_apps_returns_safe_structured_paths(self):
        apps=json.loads(self.tool.call('pc_find_apps',{'query':'editor'}))
        self.assertEqual(apps[0]['path'],'C:/Editor.lnk')

    def test_schema_exposes_real_pc_tools(self):
        names={t['function']['name'] for t in tool_schema()}
        self.assertTrue({'pc_list_windows','pc_select_window','pc_inspect_window',
                         'pc_click_control','pc_hotkey','pc_type_text','pc_click'}<=names)

    def test_native_backend_unavailable_outside_windows(self):
        import os
        if os.name!='nt':
            with self.assertRaises(DesktopUnavailable):
                WindowsDesktop().windows()

    def test_select_then_type_unicode_and_hotkey(self):
        self.assertIn('ausgewählt',self.select())
        self.assertIn('gesendet',self.tool.call('pc_type_text',{'text':'Grüße 👋 – sehr schön!'}))
        self.assertEqual(self.tool.pc.typed,['Grüße 👋 – sehr schön!'])
        self.assertIn('gesendet',self.tool.call('pc_hotkey',{'keys':'ctrl+shift+s'}))
        self.assertEqual(self.tool.pc.combos,[['ctrl','shift','s']])
        self.assertGreaterEqual(len(self.grants),3)

    def test_no_input_without_selected_window(self):
        self.assertIn('FEHLER',self.tool.call('pc_type_text',{'text':'Hi'}))
        self.assertIn('FEHLER',self.tool.call('pc_click',{'x':20,'y':30}))
        self.assertFalse(self.tool.pc.typed)
        self.assertFalse(self.tool.pc.clicked)

    def test_denial_cannot_focus_or_type(self):
        self.tool.approval=lambda *_:False
        self.assertIn('FEHLER Denied',self.select())
        self.assertIsNone(self.tool.pc.active)
        self.assertIn('FEHLER',self.tool.call('pc_type_text',{'text':'Hi'}))
        self.tool.approval=lambda *_:True
        self.select()
        self.tool.approval=lambda *_:False
        self.assertIn('FEHLER Denied',self.tool.call('pc_type_text',{'text':'Hallo'}))
        self.assertEqual(self.tool.pc.typed,[])

    def test_click_only_within_current_window(self):
        self.select()
        self.assertIn('FEHLER',self.tool.call('pc_click',{'x':9,'y':100}))
        self.assertIn('FEHLER',self.tool.call('pc_click',{'x':15,'y':480}))
        self.assertIn('FEHLER',self.tool.call('pc_click',{'x':True,'y':70}))
        self.assertEqual(self.tool.pc.clicked,[])
        self.assertIn('ausgeführt',self.tool.call('pc_click',{'x':100,'y':120}))
        self.assertEqual(self.tool.pc.clicked,[(100,120)])

    def test_control_click_requires_prior_inspection_and_reinspection(self):
        self.select()
        self.assertIn('FEHLER',self.tool.call('pc_click_control',{'control_id':1}))
        inspected=json.loads(self.tool.call('pc_inspect_window',{}))
        self.assertEqual(inspected[0]['name'],'Speichern')
        self.assertIn('angeklickt',self.tool.call('pc_click_control',{'control_id':1}))
        self.assertEqual(len(self.tool.pc.controls_clicked),1)
        self.assertIn('FEHLER',self.tool.call('pc_click_control',{'control_id':1}))

    def test_title_and_accessibility_text_not_audited(self):
        listing=self.tool.call('pc_list_windows',{})
        self.assertIn('Editor – privat',listing)
        self.select()
        self.tool.call('pc_inspect_window',{})
        self.tool.call('pc_type_text',{'text':'SENSIBLER ÜBERTRAGUNGSTEXT'})
        logs=self.store.logs(self.chat)
        self.assertFalse(any('SENSIBLER ÜBERTRAGUNGSTEXT' in x['details'] for x in logs))
        listing_result=[x['details'] for x in logs if x['event']=='tool_result' and x['details'].startswith('pc_list_windows')]
        self.assertFalse(any('Editor – privat' in x for x in listing_result))
        inspect_result=[x['details'] for x in logs if x['event']=='tool_result' and x['details'].startswith('pc_inspect_window')]
        self.assertFalse(any('Speichern' in x for x in inspect_result))

    def test_cannot_send_input_to_wrong_focus(self):
        self.select()
        def never_focus(hwnd):
            self.tool.pc.active=999
        self.tool.pc.activate=never_focus
        self.assertIn('FEHLER',self.tool.call('pc_type_text',{'text':'Hello'}))
        self.assertEqual(self.tool.pc.typed,[])

    def test_invalid_keyboard_shortcuts_blocked(self):
        self.select()
        self.assertIn('FEHLER',self.tool.call('pc_hotkey',{'keys':'ctrl+not-a-real-key'}))
        self.assertEqual(self.tool.pc.combos,[])

    def test_window_moved_during_dialog_aborts_click(self):
        self.select()
        def shift(*_):
            self.tool.pc.entry['rect']=[900,1000,1200,1400]
            return True
        self.tool.approval=shift
        self.assertIn('FEHLER',self.tool.call('pc_click',{'x':100,'y':120}))
        self.assertEqual(self.tool.pc.clicked,[])

    def test_pc_text_length_validation(self):
        self.select()
        self.assertIn('FEHLER',self.tool.call('pc_type_text',{'text':'X'*3001}))
        self.assertEqual(self.tool.pc.typed,[])


if __name__=='__main__':
    unittest.main()
