#!/usr/bin/env python3
#
# Copyright (C) 2018-2020 VyOS maintainers and contributors
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 or later as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os
import re

from sys import exit
from time import sleep

from stat import S_IRUSR, S_IWUSR, S_IRGRP
from vyos.config import Config
from vyos import ConfigError
from vyos.util import call
from vyos.template import render


ipoe_conf = '/run/accel-pppd/ipoe.conf'
ipoe_chap_secrets = '/run/accel-pppd/ipoe.chap-secrets'


def _get_cpu():
    cpu_cnt = 1
    if os.cpu_count() == 1:
        cpu_cnt = 1
    else:
        cpu_cnt = int(os.cpu_count()/2)
    return cpu_cnt


def get_config():
    c = Config()
    if not c.exists(['service', 'ipoe-server']):
        return None

    config_data = {
        'chap_secrets_file' : ipoe_chap_secrets
    }

    c.set_level(['service', 'ipoe-server'])
    config_data['interfaces'] = {}
    for intfc in c.list_nodes(['interface']):
        config_data['interfaces'][intfc] = {
            'mode': 'L2',
            'shared': '1',
            # may need a conifg option, can be dhcpv4 or up for unclassified pkts
            'sess_start': 'dhcpv4',
            'range': None,
            'ifcfg': '1',
            'vlan_mon': []
        }
        config_data['dns'] = {
            'server1': None,
            'server2': None
        }
        config_data['dnsv6'] = {
            'server1': None,
            'server2': None,
            'server3': None
        }
        config_data['ipv6'] = {
            'prfx': [],
            'pd': [],
        }
        config_data['auth'] = {
            'auth_if': {},
            'mech': 'noauth',
            'radius': {},
            'radsettings': {
                'dae-server': {}
            }
        }

        if c.exists(['interface', intfc, 'network-mode']):
            config_data['interfaces'][intfc]['mode'] = c.return_value(
                ['interface', intfc, 'network-mode'])
        if c.return_value(['interface', intfc, 'network']) == 'vlan':
            config_data['interfaces'][intfc]['shared'] = '0'
            if c.exists(['interface', intfc, 'vlan-id']):
                config_data['interfaces'][intfc]['vlan_mon'] += c.return_values(
                    ['interface', intfc, 'vlan-id'])
            if c.exists(['interface', intfc, 'vlan-range']):
                config_data['interfaces'][intfc]['vlan_mon'] += c.return_values(
                    ['interface', intfc, 'vlan-range'])
        if c.exists(['interface', intfc, 'client-subnet']):
            config_data['interfaces'][intfc]['range'] = c.return_value(
                ['interface', intfc, 'client-subnet'])
        if c.exists(['dns-server', 'server-1']):
            config_data['dns']['server1'] = c.return_value(
                ['dns-server', 'server-1'])
        if c.exists(['dns-server', 'server-2']):
            config_data['dns']['server2'] = c.return_value(
                ['dns-server', 'server-2'])
        if c.exists(['dnsv6-server', 'server-1']):
            config_data['dnsv6']['server1'] = c.return_value(
                ['dnsv6-server', 'server-1'])
        if c.exists(['dnsv6-server', 'server-2']):
            config_data['dnsv6']['server2'] = c.return_value(
                ['dnsv6-server', 'server-2'])
        if c.exists(['dnsv6-server', 'server-3']):
            config_data['dnsv6']['server3'] = c.return_value(
                ['dnsv6-server', 'server-3'])
        if not c.exists(['authentication', 'mode', 'noauth']):
            config_data['auth']['mech'] = c.return_value(
                ['authentication', 'mode'])
        if c.exists(['authentication', 'mode', 'local']):
            for auth_int in c.list_nodes(['authentication', 'interface']):
                for mac in c.list_nodes(['authentication', 'interface', auth_int, 'mac-address']):
                    config_data['auth']['auth_if'][auth_int] = {}
                    if c.exists(['authentication', 'interface', auth_int, 'mac-address',  mac, 'rate-limit']):
                        config_data['auth']['auth_if'][auth_int][mac] = {}
                        config_data['auth']['auth_if'][auth_int][mac]['up'] = c.return_value(
                            ['authentication', 'interface', auth_int, 'mac-address', mac, 'rate-limit upload'])
                        config_data['auth']['auth_if'][auth_int][mac]['down'] = c.return_value(
                            ['authentication', 'interface', auth_int, 'mac-address', 'mac', 'rate-limit download'])
                    else:
                        config_data['auth']['auth_if'][auth_int][mac] = {}
                        config_data['auth']['auth_if'][auth_int][mac]['up'] = None
                        config_data['auth']['auth_if'][auth_int][mac]['down'] = None
                    # client vlan-id
                    if c.exists(['authentication', 'interface', auth_int, 'mac-address', mac, 'vlan-id']):
                        config_data['auth']['auth_if'][auth_int][mac]['vlan'] = c.return_value(
                            ['authentication', 'interface', auth_int, 'mac-address', mac, 'vlan-id'])
        if c.exists(['authentication', 'mode',  'radius']):
            for rsrv in c.list_nodes(['authentication', 'radius-server']):
                config_data['auth']['radius'][rsrv] = {}
                if c.exists(['authentication', 'radius-server', rsrv, 'secret']):
                    config_data['auth']['radius'][rsrv]['secret'] = c.return_value(
                        ['authentication', 'radius-server', rsrv, 'secret'])
                else:
                    config_data['auth']['radius'][rsrv]['secret'] = None
                if c.exists(['authentication', 'radius-server', rsrv, 'fail-time']):
                    config_data['auth']['radius'][rsrv]['fail-time'] = c.return_value(
                        ['authentication', 'radius-server', rsrv, 'fail-time'])
                else:
                    config_data['auth']['radius'][rsrv]['fail-time'] = '0'
                if c.exists(['authentication', 'radius-server', rsrv, 'req-limit']):
                    config_data['auth']['radius'][rsrv]['req-limit'] = c.return_value(
                        ['authentication', 'radius-server', rsrv, 'req-limit'])
                else:
                    config_data['auth']['radius'][rsrv]['req-limit'] = '0'
            if c.exists(['authentication', 'radius-settings']):
                if c.exists(['authentication', 'radius-settings', 'timeout']):
                    config_data['auth']['radsettings']['timeout'] = c.return_value(
                        ['authentication', 'radius-settings', 'timeout'])
                if c.exists(['authentication', 'radius-settings', 'nas-ip-address']):
                    config_data['auth']['radsettings']['nas-ip-address'] = c.return_value(
                        ['authentication', 'radius-settings', 'nas-ip-address'])
                if c.exists(['authentication', 'radius-settings', 'nas-identifier']):
                    config_data['auth']['radsettings']['nas-identifier'] = c.return_value(
                        ['authentication', 'radius-settings', 'nas-identifier'])
                if c.exists(['authentication', 'radius-settings', 'max-try']):
                    config_data['auth']['radsettings']['max-try'] = c.return_value(
                        ['authentication', 'radius-settings', 'max-try'])
                if c.exists(['authentication', 'radius-settings', 'acct-timeout']):
                    config_data['auth']['radsettings']['acct-timeout'] = c.return_value(
                        ['authentication', 'radius-settings', 'acct-timeout'])
                if c.exists(['authentication', 'radius-settings', 'dae-server', 'ip-address']):
                    config_data['auth']['radsettings']['dae-server']['ip-address'] = c.return_value(
                        ['authentication', 'radius-settings', 'dae-server', 'ip-address'])
                if c.exists(['authentication', 'radius-settings', 'dae-server', 'port']):
                    config_data['auth']['radsettings']['dae-server']['port'] = c.return_value(
                        ['authentication', 'radius-settings', 'dae-server', 'port'])
                if c.exists(['authentication', 'radius-settings', 'dae-server', 'secret']):
                    config_data['auth']['radsettings']['dae-server']['secret'] = c.return_value(
                        ['authentication', 'radius-settings', 'dae-server', 'secret'])

        if c.exists(['client-ipv6-pool', 'prefix']):
            config_data['ipv6']['prfx'] = c.return_values(
                ['client-ipv6-pool', 'prefix'])
        if c.exists(['client-ipv6-pool', 'delegate-prefix']):
            config_data['ipv6']['pd'] = c.return_values(
                ['client-ipv6-pool', 'delegate-prefix'])

    return config_data


def generate(ipoe):
    if not ipoe:
        return None

    dirname = os.path.dirname(ipoe_conf)
    if not os.path.exists(dirname):
        os.mkdir(dirname)

    ipoe['thread_cnt'] = _get_cpu()
    render(ipoe_conf, 'ipoe-server/ipoe.config.tmpl', ipoe, trim_blocks=True)

    if ipoe['auth']['mech'] == 'local':
        render(ipoe_chap_secrets, 'ipoe-server/chap-secrets.tmpl', ipoe)
        os.chmod(ipoe_chap_secrets, S_IRUSR | S_IWUSR | S_IRGRP)

    else:
        if os.path.exists(ipoe_chap_secrets):
             os.unlink(ipoe_chap_secrets)

    return None


def verify(c):
    if c == None or not c:
        return None

    if not c['interfaces']:
        raise ConfigError("service ipoe-server interface requires a value")

    for intfc in c['interfaces']:
        if not c['interfaces'][intfc]['range']:
            raise ConfigError("service ipoe-server interface " +
                              intfc + " client-subnet needs a value")

    if c['auth']['mech'] == 'radius':
        if not c['auth']['radius']:
            raise ConfigError(
                "service ipoe-server authentication radius-server requires a value for authentication mode radius")
        else:
            for radsrv in c['auth']['radius']:
                if not c['auth']['radius'][radsrv]['secret']:
                    raise ConfigError(
                        "service ipoe-server authentication radius-server " + radsrv + " secret requires a value")

    if c['auth']['radsettings']['dae-server']:
        try:
            if c['auth']['radsettings']['dae-server']['ip-address']:
                pass
        except:
            raise ConfigError(
                "service ipoe-server authentication radius-settings dae-server ip-address value required")
        try:
            if c['auth']['radsettings']['dae-server']['secret']:
                pass
        except:
            raise ConfigError(
                "service ipoe-server authentication radius-settings dae-server secret value required")
        try:
            if c['auth']['radsettings']['dae-server']['port']:
                pass
        except:
            raise ConfigError(
                "service ipoe-server authentication radius-settings dae-server port value required")

    if len(c['ipv6']['pd']) != 0 and len(c['ipv6']['prfx']) == 0:
        raise ConfigError(
            "service ipoe-server client-ipv6-pool prefix needs a value")

    return c


def apply(ipoe):
    if ipoe == None:
        call('systemctl stop accel-ppp@ipoe.service')

        if os.path.exists(ipoe_conf):
             os.unlink(ipoe_conf)

        if os.path.exists(ipoe_chap_secrets):
             os.unlink(ipoe_chap_secrets)

        return None

    call('systemctl restart accel-ppp@ipoe.service')


if __name__ == '__main__':
    try:
        c = get_config()
        verify(c)
        generate(c)
        apply(c)
    except ConfigError as e:
        print(e)
        exit(1)
