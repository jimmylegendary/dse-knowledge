"""Install the current checkout's user service; run after provider/database setup."""
from pathlib import Path
import os,subprocess
root=Path(__file__).resolve().parents[1]
unit=Path.home()/'.config/systemd/user/dse-knowledge.service'
unit.parent.mkdir(parents=True,exist_ok=True)
unit.write_text((root/'deploy/dse-knowledge.service.in').read_text().replace('@REPOSITORY@',str(root)))
env=os.environ.copy();runtime=f'/run/user/{os.getuid()}'
env['XDG_RUNTIME_DIR']=runtime;env['DBUS_SESSION_BUS_ADDRESS']='unix:path='+runtime+'/bus'
for args in (['daemon-reload'],['enable','--now','dse-knowledge.service']):
    subprocess.run(['systemctl','--user',*args],env=env,check=True)
print('dse-knowledge.service installed and started')
