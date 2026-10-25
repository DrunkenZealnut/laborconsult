"""Compile the scripts the HTML parser actually delivers to the browser."""
from html.parser import HTMLParser
from pathlib import Path
import subprocess
import unittest

class Scripts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.scripts=[];self.current=None
    def handle_starttag(self,tag,attrs):
        if tag=='script':
            attrs=dict(attrs)
            kind=attrs.get('type','')
            if 'src' not in attrs and kind in {'','text/javascript','application/javascript','module'}:
                self.current={'line':self.getpos()[0],'kind':kind,'text':''}
    def handle_data(self,data):
        if self.current is not None:self.current['text']+=data
    def handle_endtag(self,tag):
        if tag=='script' and self.current is not None:
            self.scripts.append(self.current);self.current=None

class PublicScriptTests(unittest.TestCase):
    def test_actual_public_inline_scripts_compile(self):
        count=0
        for path in sorted((Path(__file__).parent/'public').rglob('*.html')):
            parser=Scripts();parser.feed(path.read_text());parser.close()
            for script in parser.scripts:
                if not script['text'].strip():continue
                count+=1
                with self.subTest(page=path.name,line=script['line']):
                    kind='module' if script['kind']=='module' else 'commonjs'
                    result=subprocess.run(['node','--check','--input-type='+kind],input=script['text'],text=True,capture_output=True)
                    self.assertEqual(result.returncode,0,result.stderr)
        self.assertGreater(count,0,'HTML script discovery silently stopped')

if __name__=='__main__':unittest.main()
