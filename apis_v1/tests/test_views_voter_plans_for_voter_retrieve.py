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
        self.voter_plans_for_voter_retrieve_url = reverse('apis_v1:voterPlansForVoterRetrieveView')

    def test_retrieve_with_no_voter_device_id(self):
        response = self.client.get(self.voter_plans_for_voter_retrieve_url)
        json_data = json.loads(response.content.decode())
        self.assertEqual('status' in json_data, True, "status expected in the json response, and not found")
        self.assertEqual(json_data['status'], 'VOTER_PLANS_RETRIEVE_MISSING_VOTER_WE_VOTE_ID')