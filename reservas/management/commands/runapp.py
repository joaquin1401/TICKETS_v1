import subprocess
import sys
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = 'Runs both the development server and the qcluster background worker'

    def add_arguments(self, parser):
        # Allow an optional address/port argument (like 0.0.0.0:8000)
        parser.add_argument('addrport', nargs='?', default='', help='Optional port number, or ipaddr:port')

    def handle(self, *args, **options):
        addrport = options.get('addrport', '')
        self.stdout.write(self.style.SUCCESS(f'Starting runserver{" " + addrport if addrport else ""} and qcluster...'))

        # Build the runserver command
        runserver_args = [sys.executable, 'manage.py', 'runserver']
        if addrport:
            runserver_args.append(addrport)

        # Start the Django development server
        server_process = subprocess.Popen(runserver_args)

        # Start the qcluster worker
        qcluster_process = subprocess.Popen([sys.executable, 'manage.py', 'qcluster'])

        try:
            # Wait for both processes
            server_process.wait()
            qcluster_process.wait()
        except KeyboardInterrupt:
            # Handle Ctrl+C gracefully to kill both
            self.stdout.write(self.style.WARNING('\nStopping both processes...'))
            server_process.terminate()
            qcluster_process.terminate()
            
            server_process.wait()
            qcluster_process.wait()
            self.stdout.write(self.style.SUCCESS('Processes stopped.'))
