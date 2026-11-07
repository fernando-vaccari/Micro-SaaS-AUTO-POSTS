"""Consistent online SQLite backup. APP_SECRET must be backed up separately."""
import argparse
from datetime import datetime,timezone
from pathlib import Path
import sqlite3
import os
from autoposts import core

def backup(destination):
    destination=Path(destination).resolve()
    if destination.exists():raise FileExistsError('O destino já existe; não será sobrescrito.')
    destination.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(destination,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    os.close(fd)
    with core.connect() as source:
        with sqlite3.connect(destination) as target:
            source.backup(target)
            if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Backup inválido.')
    destination.chmod(0o600)
    return destination

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('destination');args=parser.parse_args()
    backup(args.destination);print('Backup SQLite consistente concluído. Preserve APP_SECRET em um cofre separado.')
