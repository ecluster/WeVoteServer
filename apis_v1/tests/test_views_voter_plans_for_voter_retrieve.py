# apis_v1/test_views_voter_plans_for_voter_retrieve
# Brought to you by We Vote. Be good.


from django.urls import reverse
from django.test import TestCase

import json

class WeVoteAPIsV1TestsVoterPlansForVoterRetrieve(TestCase):
    databases = ["default", "readonly"]
    
    def setUp(self):
        self.generate_voter_device_id_url = reverse("apis_v1:deviceIdGenerateView")
        self.voter_create_url = reverse("apis_v1:voterCreateView")
    