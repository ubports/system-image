where=udm/build
root=/home/barry/projects/phone/${where}/src/downloads/daemon
logfile=/home/barry/.cache/ubuntu-download-manager/ubuntu-download-manager.INFO
# export GLOG_logtostderr=1
# export GLOG_v=100
echo -n `date --rfc-3339=ns` >> ${logfile}
echo -n " " >> ${logfile}
echo $* >> ${logfile}
#exec env -u DBUS_SESSION_BUS_ADDRESS ${root}/ubuntu-download-manager $*
exec ${root}/ubuntu-download-manager $*
