import sys
import shutil
import subprocess
import os
import signal
import urllib2
import traceback
import time

from colorama import Fore, Style

CONF_URL_NORMAL="https://raw.githubusercontent.com/mpillar/aerofs-upstart/master/aerofs.conf"
CONF_URL_TS="https://raw.githubusercontent.com/mpillar/aerofs-upstart/master/aerofsts.conf"

# ------------------------------------------------------------
# Signal Handling
# ------------------------------------------------------------

def global_signal_handler(s, f):
    print
    bail("Received signal")

def init_global_signal_handler():
    signal.signal(signal.SIGINT, global_signal_handler)

def bail(message):
    print
    print Fore.RED + message + ". Aborting." + Style.RESET_ALL
    sys.exit(1)

# ------------------------------------------------------------
# User I/O utilities
# ------------------------------------------------------------

def get_selection(allowed):
    allowed_map = {}
    for a in allowed:
        allowed_map[str(a)] = a
    while True:
        sys.stdout.write("Enter a number " + str(allowed) + ": ")
        selection = raw_input()
        if selection in allowed_map:
            sys.stdout.write("Selection " + selection + " okay? [Y/n] ")
            confirm = raw_input()
            if confirm == "Y":
                return allowed_map[selection]

def get_text(prompt):
    while True:
        sys.stdout.write(prompt + ": ")
        text = raw_input()
        sys.stdout.write(prompt + " \"" + text + "\" okay? [Y/n] ")
        confirm = raw_input()
        if confirm == "Y":
            return text

# ------------------------------------------------------------
# Network
# ------------------------------------------------------------

def chunk_report(bytes_so_far, chunk_size, total_size):
   percent = float(bytes_so_far) / total_size
   percent = round(percent*100, 2)
   sys.stdout.write("Downloaded %d of %d bytes (%0.2f%%)\r" % (bytes_so_far, total_size, percent))
   if bytes_so_far >= total_size: sys.stdout.write('\n')

def chunk_read(response, local_file, chunk_size=32728, report_hook=None):
   total_size = response.info().getheader('Content-Length').strip()
   total_size = int(total_size)
   bytes_so_far = 0
   while True:
      chunk = response.read(chunk_size)
      local_file.write(chunk)
      bytes_so_far += len(chunk)
      if not chunk: break
      if report_hook: report_hook(bytes_so_far, chunk_size, total_size)
   return bytes_so_far

# ------------------------------------------------------------
# Infrastructure Related Utils
# ------------------------------------------------------------

def construct_installer_url(config):
    root = "https://" + config["host"] + "/static/installers"
    version = urllib2.urlopen(root + "/current.ver").read().split('=')[1].strip()
    url =  root + "/aerofs%s-installer-%s.tgz" % (("ts" if config["ts"] else ""), version)
    return url

def download_installer_from(config, url):
    response = urllib2.urlopen(url)
    basename = os.path.join("/tmp", config["host"] + "-" + os.path.basename(url))
    # Do no re-download if we already have the installer on our system.
    if os.path.isfile(basename): return basename
    with open(basename, "wb") as local_file:
        chunk_read(response, local_file, report_hook=chunk_report)
    return basename

def get_service_name(config):
    return "aerofsts" if config["ts"] else "aerofs"

def install_aerofs_tar(filename):
    os.chdir('/tmp')
    subprocess.check_call(("tar xf %s" % filename).split(' '))
    if os.path.isdir('/opt/aerofs'): shutil.rmtree('/opt/aerofs')
    shutil.move('/tmp/aerofs', '/opt/aerofs')

def run_cli(config):
    global cli_process
    executable = "/opt/aerofs/aerofsts-cli" if config["ts"] else "/opt/aerofs/aerofs-cli"
    cli_process = subprocess.Popen("su aerofs -c %s" % executable, shell=True)
    time.sleep(2.0)
    while cli_process.poll() is None:
        time.sleep(0.5)
        # When the "setting up" flag is deleted, we can proceed.
        if cert_exists(config) and not su_exists(config):
            with open(os.devnull, "w") as f:
                subprocess.call("pkill -u aerofs".split(' '), stdout=f, stderr=f)
                break

def aerofs_internal_exists(config, filename):
    ts = '/home/aerofs/.aerofsts/' + filename
    no_ts = '/home/aerofs/.aerofs/' + filename
    fully_qualified_filename = ts if config["ts"] else no_ts
    return os.path.isfile(fully_qualified_filename)

def su_exists(config):
    return aerofs_internal_exists(config, 'su')

def cert_exists(config):
    return aerofs_internal_exists(config, 'cert')

def create_aerofs_user_if_needed():
    null = open(os.devnull, 'w')
    if subprocess.call("id -u aerofs".split(' '), stdout=null, stderr=subprocess.STDOUT) != 0:
        subprocess.check_call("useradd -m -d /home/aerofs -s /bin/bash aerofs".split(' '))

def download_and_install_upstart(config):
    conf_url = CONF_URL_TS if config["ts"] else CONF_URL_NORMAL
    conf_file = "/etc/init/aerofsts.conf" if config["ts"] else "/etc/init/aerofs.conf"
    with open(conf_file, "wb") as local_file:
        local_file.write(urllib2.urlopen(conf_url).read())
    if not os.path.isfile("/etc/init.d/%s" % get_service_name(config)):
        subprocess.check_call(("ln -s /lib/init/upstart-job /etc/init.d/%s" % get_service_name(config)).split(' '))
    subprocess.check_call(("sudo update-rc.d %s defaults" % get_service_name(config)).split(' '))

def start_aerofs_service(config):
    subprocess.check_call(("service %s start" % get_service_name(config)).split(' '))

def check_if_service_exist(config):
    service_name = get_service_name(config)
    return True if subprocess.call(("service %s status" % service_name).split(' ')) == 0 else False

def restart_the_service(config):
    subprocess.call(("sudo service %s restart" % get_service_name(config)).split(' '))

# ------------------------------------------------------------
# User Interaction Section
# ------------------------------------------------------------

def main():
    config = {}
    print Fore.GREEN + "AeroFS Quick Installation Utility" + Style.RESET_ALL
    print "The easist, fastest way to install AeroFS on headless Ubuntu systems."

    if os.getuid() != 0: bail("Must be run as root")

    print
    print Fore.GREEN + "Which AeroFS Service would you like to install?" + Style.RESET_ALL
    print "[0] AeroFS Team Server"
    print "[1] AeroFS Desktop Client"
    config["ts"] = True if get_selection([0, 1]) is 0 else False

    print
    print Fore.GREEN + "Please enter the DNS hostname of your Appliance." + Style.RESET_ALL
    config["host"] = get_text("PC Appliance DNS Host")

    print
    print Fore.GREEN + "Downloading and installing AeroFS..." + Style.RESET_ALL
    installer_url = construct_installer_url(config)
    installer_filename = download_installer_from(config, installer_url)
    install_aerofs_tar(installer_filename)

    print
    print Fore.GREEN + "Creating aerofs user..." + Style.RESET_ALL
    create_aerofs_user_if_needed()

    service_exist = check_if_service_exist(config)

    if not service_exist:
        print
        print Fore.GREEN + "Running AeroFS installation program..." + Style.RESET_ALL
        run_cli(config)
        if su_exists(config) or not cert_exists(config):
            bail("It looks like your setup never finished")

        print
        print Fore.GREEN + "Downloading and installing upstart script..." + Style.RESET_ALL
        download_and_install_upstart(config)

        print
        print Fore.GREEN + "Starting AeroFS Service..." + Style.RESET_ALL
        start_aerofs_service(config)
    else:
        print
        print Fore.GREEN + "Client installed and updated. Restarting service..." + Style.RESET_ALL
        restart_the_service(config)

    service_name = get_service_name(config)
    print "Manage with: " + Fore.BLUE + "sudo service " + service_name + " <stop|start|restart|status>" + Style.RESET_ALL

    print
    print Fore.GREEN + "Installation complete!" + Style.RESET_ALL
    print "Thanks for using the AeroFS Quick Installation Utility!"
    print

# ------------------------------------------------------------
# Entry Point
# ------------------------------------------------------------

if __name__ == "__main__":
    try:
        init_global_signal_handler()
        main()
    except SystemExit as e:
        raise e
    except:
        print
        print Fore.RED + "Exception caught. Aborting." + Style.RESET_ALL
        traceback.print_exc(file=sys.stdout)
        sys.exit(1)
