URL_BASE = 'https://www.googleapis.com/compute/v1/projects/'

def GenerateConfig(context):
  deployment = context.env['deployment']
  clusterName = context.properties['clusterName']
  region = context.properties['region']
  groupName = context.properties['groupName']
  machineCount = context.properties['machineCount']
  machineType = context.properties['machineType']
  diskSize = context.properties['diskSize']

  items = []
  items.append({'key':'startup-script', 'value':GenerateStartupScript()})
  metadata = {'items': items}

  it_name = deployment + '-' + clusterName + '-' + groupName + '-it'
  it = {
    'name': it_name,
    'type': 'compute.v1.instanceTemplate',
    'properties': {
      'properties': {
        'machineType': machineType,
        'networkInterfaces': [{
          'network': URL_BASE + context.env['project'] + '/global/networks/default',
          'accessConfigs': [{
            'name': 'External NAT',
            'type': 'ONE_TO_ONE_NAT'
          }]
        }],
        'disks': [{
          'deviceName': 'boot',
          'type': 'PERSISTENT',
          'boot': True,
          'autoDelete': True,
          'initializeParams': {
            'sourceImage': URL_BASE + 'ubuntu-os-cloud/global/images/ubuntu-1404-trusty-v20170424'
          },
          'diskType': 'pd-ssd',
          'diskSizeGb': diskSize
        }],
        'metadata': metadata,
      }
    }
  }

  igm = {
    'name': deployment + '-' + clusterName + '-' + groupName + '-igm',
    'type': 'compute.v1.regionInstanceGroupManager',
    'properties': {
      'region': region,
      'baseInstanceName': deployment + '-' + clusterName + '-' + groupName + '-instance',
      'instanceTemplate': '$(ref.' + it_name + '.selfLink)',
      'targetSize': machineCount,
      'autoHealingPolicies': [{
        'initialDelaySec': 60
      }]
    }
  }

  resources = []
  resources.append(it)
  resources.append(igm)
  return {'resources': resources}

install='''
#!/usr/bin/env bash

echo "Running install.sh"

wget http://packages.couchbase.com/releases/4.6.1/couchbase-server-enterprise_4.6.1-ubuntu14.04_amd64.deb

# Using these instructions
# https://developer.couchbase.com/documentation/server/4.6/install/ubuntu-debian-install.html
dpkg -i couchbase-server-enterprise_4.6.1-ubuntu14.04_amd64.deb
apt-get update
apt-get -y install couchbase-server

#######################################################
############ Turn Off Transparent Hugepages ###########
#######################################################

# Please look at http://bit.ly/1ZAcLjD as for how to PERMANENTLY alter this setting.

echo "#!/bin/bash
### BEGIN INIT INFO
# Provides:          disable-thp
# Required-Start:    $local_fs
# Required-Stop:
# X-Start-Before:    couchbase-server
# Default-Start:     2 3 4 5
# Default-Stop:      0 1 6
# Short-Description: Disable THP
# Description:       disables Transparent Huge Pages (THP) on boot
### END INIT INFO

echo 'never' > /sys/kernel/mm/transparent_hugepage/enabled
echo 'never' > /sys/kernel/mm/transparent_hugepage/defrag
" > /etc/init.d/disable-thp
chmod 755 /etc/init.d/disable-thp
service disable-thp start
update-rc.d disable-thp defaults

#######################################################
################# Set Swappiness to 0 #################
#######################################################

# Please look at http://bit.ly/1k2CtNn as for how to PERMANENTLY alter this setting.

sysctl vm.swappiness=0
echo "
# Required for Couchbase
vm.swappiness = 0" >> /etc/sysctl.conf
'''

configure = '''
echo "Running configure.sh"

echo "Using the settings:"
echo adminUsername \'$adminUsername\'
echo adminPassword \'$adminPassword\'

rallyPrivateDNS=''
nodePrivateDNS=`curl -s -H "Metadata-Flavor: Google" "http://metadata.google.internal/computeMetadata/v1/instance`

cd /opt/couchbase/bin/

echo "Running couchbase-cli node-init"
./couchbase-cli node-init \
  --cluster=$nodePrivateDNS \
  --node-init-hostname=$nodePrivateDNS \
  --node-init-data-path=/mnt/datadisk/data \
  --node-init-index-path=/mnt/datadisk/index \
  --user=$adminUsername \
  --pass=$adminPassword

if [[ $rallyPrivateDNS == $nodePrivateDNS ]]
then
  totalRAM=$(grep MemTotal /proc/meminfo | awk '{print $2}')
  dataRAM=$((50 * $totalRAM / 100000))
  indexRAM=$((15 * $totalRAM / 100000))

  echo "Running couchbase-cli cluster-init"
  ./couchbase-cli cluster-init \
    --cluster=$nodePrivateDNS \
    --cluster-ramsize=$dataRAM \
    --cluster-index-ramsize=$indexRAM \
    --cluster-username=$adminUsername \
    --cluster-password=$adminPassword \
    --services=data,index,query,fts
else
  echo "Running couchbase-cli server-add"
  output=""
  while [[ $output != "Server $nodePrivateDNS:8091 added" && ! $output =~ "Node is already part of cluster." ]]
  do
    vm0PrivateDNS=`host vm0 | awk '{print $1}'`
    output=`./couchbase-cli server-add \
      --cluster=$rallyPrivateDNS \
      --user=$adminUsername \
      --pass=$adminPassword \
      --server-add=$nodePrivateDNS \
      --server-add-username=$adminUsername \
      --server-add-password=$adminPassword \
      --services=data,index,query,fts`
    echo server-add output \'$output\'
    sleep 10
  done

  echo "Running couchbase-cli rebalance"
  output=""
  while [[ ! $output =~ "SUCCESS" ]]
  do
    output=`./couchbase-cli rebalance \
      --cluster=$rallyPrivateDNS \
      --user=$adminUsername \
      --pass=$adminPassword`
    echo rebalance output \'$output\'
    sleep 10
  done

fi
'''

def GenerateStartupScript():
    script = install

    script+='''
    adminUsername='couchbase'
    adminPassword='foo123!'
    '''

    script+=configure
    return script
