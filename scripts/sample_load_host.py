"""Private host-level supplemental measurements; concurrent work is not isolated."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import time


def run(*command):
    result=subprocess.run(command,text=True,capture_output=True)
    return {'exit_code':result.returncode,'stdout':result.stdout.strip(),'stderr':result.stderr.strip()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--watch-pid',type=int,required=True);parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    with args.output.open('x',buffering=1) as output:
        while subprocess.run(['kill','-0',str(args.watch_pid)],capture_output=True).returncode==0:
            record={'at':time.time(),'host_only':True,'vm_stat':run('vm_stat'),
                    'network':run('netstat','-ib'),'disk_io_since_boot':run('iostat','-d','-c','1'),'databases':{}}
            for path in args.root.glob('*.sqlite3'):
                started=time.monotonic()
                item={'bytes':path.stat().st_size}
                try:
                    with closing(sqlite3.connect(f'file:{path}?mode=ro',uri=True,timeout=.1)) as connection:
                        tables=[r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")]
                        item['rows']={table:connection.execute('SELECT count(*) FROM "'+table.replace('"','""')+'"').fetchone()[0] for table in tables}
                except sqlite3.Error as error:item['error']=str(error)
                item['probe_seconds']=time.monotonic()-started
                record['databases'][path.name]=item
            output.write(json.dumps(record)+'\n')
            time.sleep(15)


if __name__=='__main__':main()
