import json
from django.db import models, IntegrityError
from ad_manager.util import monitoring_client
from lib.topology import Topology


class SelectRelatedModelManager(models.Manager):
    def __init__(self, *args):
        super(SelectRelatedModelManager, self).__init__()
        self.related_fields = args

    def get_queryset(self):
        queryset = super(SelectRelatedModelManager, self).get_queryset()
        return queryset.select_related(*self.related_fields)


class ISD(models.Model):
    id = models.CharField(max_length=50, primary_key=True)

    def __str__(self):
        return str(self.id)

    class Meta:
        verbose_name = 'ISD'


class AD(models.Model):
    id = models.CharField(max_length=50, primary_key=True)
    isd = models.ForeignKey('ISD')
    is_core_ad = models.BooleanField(default=False)

    # Use custom model manager with select_related()
    objects = SelectRelatedModelManager('isd')

    def query_ad_status(self):
        return monitoring_client.get_ad_info(self.isd_id, self.id)

    def get_remote_topology(self):
        topology_str = monitoring_client.get_topology(self.isd_id, self.id)
        if topology_str:
            topology_dict = json.loads(topology_str)
            return topology_dict
        else:
            return None

    def generate_topology_dict(self):
        out_dict = {'ISDID': int(self.isd_id), 'ADID': int(self.id),
                    'Core': int(self.is_core_ad),
                    'EdgeRouters': {}, 'PathServers': {}, 'BeaconServers': {},
                    'CertificateServers': {},
        }
        for i, router in enumerate(self.routerweb_set.all(), start=1):
            out_dict['EdgeRouters'][str(i)] = router.get_dict()
        for i, ps in enumerate(self.pathserverweb_set.all(), start=1):
            out_dict['PathServers'][str(i)] = ps.get_dict()
        for i, bs in enumerate(self.beaconserverweb_set.all(), start=1):
            out_dict['BeaconServers'][str(i)] = bs.get_dict()
        for i, cs in enumerate(self.certificateserverweb_set.all(), start=1):
            out_dict['CertificateServers'][str(i)] = cs.get_dict()
        return out_dict

    def fill_from_topology(self, topology, clear=False):
        assert isinstance(topology, Topology), \
            'Instance of the Topology class is required'

        if clear:
            self.routerweb_set.all().delete()
            self.pathserverweb_set.all().delete()
            self.certificateserverweb_set.all().delete()
            self.beaconserverweb_set.all().delete()

        routers = topology.get_all_edge_routers()
        beacon_servers = topology.beacon_servers
        certificate_servers = topology.certificate_servers
        path_servers = topology.path_servers

        try:
            for router in routers:
                interface = router.interface
                neighbor_ad = AD.objects.get(id=interface.neighbor_ad,
                                             isd=interface.neighbor_isd)
                router_element = RouterWeb(addr=router.addr, ad=self,
                                           neighbor_ad=neighbor_ad,
                                           neighbor_type=interface.neighbor_type)
                router_element.save()

            for bs in beacon_servers:
                bs_element = BeaconServerWeb(addr=bs.addr, ad=self)
                bs_element.save()

            for cs in certificate_servers:
                cs_element = CertificateServerWeb(addr=cs.addr, ad=self)
                cs_element.save()

            for ps in path_servers:
                ps_element = PathServerWeb(addr=ps.addr, ad=self)
                ps_element.save()
        except IntegrityError as ex:
            pass


    def __str__(self):
        return '{}-{}'.format(self.isd.id, self.id)

    class Meta:
        verbose_name = 'AD'


class SCIONWebElement(models.Model):
    addr = models.IPAddressField()
    ad = models.ForeignKey(AD)

    def id_str(self):
        # FIXME counter
        return "{}{}-{}-1".format(self.prefix, self.ad.isd_id, self.ad_id)

    def get_dict(self):
        return {'AddrType': 'IPv4', 'Addr': self.addr}

    def __str__(self):
        return '{} -- {}'.format(self.ad, self.addr)

    class Meta:
        abstract = True


class BeaconServerWeb(SCIONWebElement):
    prefix = 'bs'

    class Meta:
        verbose_name = 'Beacon server'
        unique_together = (("ad", "addr"),)


class CertificateServerWeb(SCIONWebElement):
    prefix = 'cs'

    class Meta:
        verbose_name = 'Certificate server'
        unique_together = (("ad", "addr"),)


class PathServerWeb(SCIONWebElement):
    prefix = 'ps'

    class Meta:
        verbose_name = 'Path server'
        unique_together = (("ad", "addr"),)


class RouterWeb(SCIONWebElement):
    NEIGHBOR_TYPES = (
        ('CHILD',) * 2,
        ('PARENT',) * 2,
        ('PEER',) * 2,
        ('ROUTING',) * 2,
    )

    neighbor_ad = models.ForeignKey(AD, related_name='neighbors')
    neighbor_type = models.CharField(max_length=10, choices=NEIGHBOR_TYPES)

    def id_str(self):
        return "er{}-{}er{}-{}".format(self.ad.isd_id, self.ad_id,
                                       self.neighbor_ad.isd_id,
                                       self.neighbor_ad.id)

    def get_dict(self):
        out_dict = super(RouterWeb, self).get_dict()
        out_dict['Interface'] = {'NeighborType': self.neighbor_type,
                                 'NeighborISD': int(self.neighbor_ad.isd_id),
                                 'NeighborAD': int(self.neighbor_ad.id)}
        return out_dict

    class Meta:
        verbose_name = 'Router'
        unique_together = (("ad", "addr"),)
