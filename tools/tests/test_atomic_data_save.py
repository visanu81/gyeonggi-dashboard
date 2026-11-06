import ast
import builtins
import errno
import io
import json
import os
import re
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / 'update_data.py'


def load_save_functions(output_path):
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    wanted = {'_atomic_write_text', 'save_data'}
    functions = [node for node in tree.body
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and node.name in wanted]
    namespace = {
        'Path': Path,
        'os': os,
        'OUTPUT_PATH': output_path,
        'datetime': datetime,
        'json': json,
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(SOURCE), 'exec'), namespace)
    return namespace['save_data']


class AtomicDataSaveTests(unittest.TestCase):
    def test_success_keeps_header_timestamp_compact_json_and_korean(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'data.js'
            data = {'지역': '경기도', '상태': ['맑음', '비']}
            load_save_functions(output)(data)

            content = output.read_text(encoding='utf-8')
            match = re.fullmatch(
                r'// 자동 생성\. 마지막 갱신: (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\n'
                r'window\.DASHBOARD_DATA = (.*);\n', content)
            self.assertIsNotNone(match)
            datetime.strptime(match.group(1), '%Y-%m-%d %H:%M:%S')
            self.assertEqual(match.group(2), json.dumps(data, ensure_ascii=False, separators=(',', ':')))
            self.assertEqual(json.loads(match.group(2)), data)

    def test_partial_temp_write_enospc_preserves_old_output_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'data.js'
            old_content = '// 이전 정상 데이터\nwindow.DASHBOARD_DATA = {"ok":true};\n'
            output.write_text(old_content, encoding='utf-8')
            original_builtin_open = builtins.open
            original_io_open = io.open

            class PartialWriteFailure:
                def __init__(self, file):
                    self.file = file

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    self.file.close()

                def write(self, text):
                    self.file.write(text[:12])
                    self.file.flush()
                    raise OSError(errno.ENOSPC, 'No space left on device')

                def __getattr__(self, name):
                    return getattr(self.file, name)

            def fail_partial_write(open_func, file, mode='r', *args, **kwargs):
                opened = open_func(file, mode, *args, **kwargs)
                path = Path(file)
                if path.parent == output.parent and any(flag in mode for flag in 'wax+'):
                    return PartialWriteFailure(opened)
                return opened

            def patched_builtin_open(file, mode='r', *args, **kwargs):
                return fail_partial_write(original_builtin_open, file, mode, *args, **kwargs)

            def patched_io_open(file, mode='r', *args, **kwargs):
                return fail_partial_write(original_io_open, file, mode, *args, **kwargs)

            with patch.object(builtins, 'open', patched_builtin_open), \
                    patch.object(io, 'open', patched_io_open):
                with self.assertRaises(OSError) as raised:
                    load_save_functions(output)({'ok': False})
            self.assertEqual(raised.exception.errno, errno.ENOSPC)

            self.assertEqual(output.read_text(encoding='utf-8'), old_content)
            self.assertEqual(list(Path(directory).iterdir()), [output])


if __name__ == '__main__':
    unittest.main()
