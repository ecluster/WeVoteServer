# organization/views_admin.py
# Brought to you by We Vote. Be good.
# -*- coding: UTF-8 -*-

from .controllers import full_domain_string_available, merge_these_two_organizations,\
    move_organization_followers_to_another_organization, move_organization_membership_link_to_another_organization, \
    organizations_import_from_master_server, \
    push_organization_data_to_other_table_caches, subdomain_string_available
from .models import GROUP, INDIVIDUAL, Organization, OrganizationReservedDomain, ORGANIZATION_UNIQUE_IDENTIFIERS
from admin_tools.views import redirect_to_sign_in_page
from candidate.models import CandidateCampaign, CandidateCampaignListManager, CandidateCampaignManager
from config.base import get_environment_variable
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.messages import get_messages
from django.shortcuts import render
from donate.models import MasterFeaturePackage
from exception.models import handle_record_found_more_than_one_exception,\
    handle_record_not_deleted_exception, handle_record_not_found_exception
from election.controllers import retrieve_upcoming_election_id_list
from election.models import Election, ElectionManager
from import_export_twitter.controllers import refresh_twitter_organization_details
from import_export_vote_smart.models import VoteSmartSpecialInterestGroupManager
from issue.models import ALPHABETICAL_ASCENDING, IssueListManager, IssueManager, \
    OrganizationLinkToIssueList, OrganizationLinkToIssueManager, MOST_LINKED_ORGANIZATIONS
from measure.models import ContestMeasure, ContestMeasureListManager, ContestMeasureManager
from office.models import ContestOfficeManager
import operator
from organization.models import OrganizationListManager, OrganizationManager, ORGANIZATION_TYPE_MAP, UNKNOWN
from organization.controllers import figure_out_organization_conflict_values, \
    organization_retrieve_tweets_from_twitter, organization_analyze_tweets
from position.models import PositionEntered, PositionForFriends, PositionListManager, PositionManager, \
    INFORMATION_ONLY, OPPOSE, STILL_DECIDING, SUPPORT
from twitter.models import TwitterUserManager
from voter.models import retrieve_voter_authority, voter_has_authority, VoterManager
from voter_guide.models import VoterGuideManager
import wevote_functions.admin
from wevote_functions.functions import convert_to_int, extract_twitter_handle_from_text_string, positive_value_exists, \
    STATE_CODE_MAP
from django.http import HttpResponse
import json


ORGANIZATION_STANCE_CHOICES = (
    (SUPPORT,           'We Support'),
    (OPPOSE,            'We Oppose'),
    (INFORMATION_ONLY,  'Information Only - No stance'),
    (STILL_DECIDING,    'We Are Still Deciding Our Stance'),
)
ORGANIZATIONS_SYNC_URL = get_environment_variable("ORGANIZATIONS_SYNC_URL")  # organizationsSyncOut
WE_VOTE_SERVER_ROOT_URL = get_environment_variable("WE_VOTE_SERVER_ROOT_URL")

logger = wevote_functions.admin.get_logger(__name__)


@login_required
def compare_two_organizations_for_merge_view(request):
    # admin, analytics_admin, partner_organization, political_data_manager, political_data_viewer, verified_volunteer
    authority_required = {'political_data_manager'}
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    organization1_we_vote_id = request.GET.get('organization1_we_vote_id', 0)
    organization2_we_vote_id = request.GET.get('organization2_we_vote_id', 0)
    google_civic_election_id = request.GET.get('google_civic_election_id', 0)
    google_civic_election_id = convert_to_int(google_civic_election_id)

    organization_manager = OrganizationManager()
    organization_results = organization_manager.retrieve_organization_from_we_vote_id(organization1_we_vote_id)
    if not organization_results['organization_found']:
        messages.add_message(request, messages.ERROR, "Organization1 not found.")
        return HttpResponseRedirect(reverse('organization:organization_list', args=()) +
                                    "?google_civic_election_id=" + str(google_civic_election_id))

    organization_option1_for_template = organization_results['organization']

    organization_results = organization_manager.retrieve_organization_from_we_vote_id(organization2_we_vote_id)
    if not organization_results['organization_found']:
        messages.add_message(request, messages.ERROR, "Organization2 not found.")
        return HttpResponseRedirect(reverse('organization:organization_position_list',
                                            args=(organization_option1_for_template.id,)) +
                                    "?google_civic_election_id=" + str(google_civic_election_id))

    organization_option2_for_template = organization_results['organization']

    organization_merge_conflict_values = figure_out_organization_conflict_values(
        organization_option1_for_template, organization_option2_for_template)

    # This view function takes us to displaying a template
    remove_duplicate_process = False  # Do not try to find another office to merge after finishing
    return render_organization_merge_form(
        request, organization_option1_for_template,
        organization_option2_for_template,
        organization_merge_conflict_values,
        remove_duplicate_process)

@login_required
def organization_analyze_tweets_view(request, organization_we_vote_id):
    """

    :param request:
    :param organization_we_vote_id:
    :return:
    """
    google_civic_election_id = convert_to_int(request.GET.get('google_civic_election_id', 0))
    state_code = request.GET.get('state_code', False)

    org_hashtags = organization_analyze_tweets(organization_we_vote_id)
    messages.add_message(request, messages.INFO, 'Tweets stored locally: {cached_tweets}, '
                                                 'Hash tags retrieved: {hash_tags_retrieved}, '
                                                 'Number of unique hashtags found in cached tweets: '
                                                 '{unique_hashtags}, '
                                                 'Organization links to hashtags: '
                                                 '{organization_link_to_hashtag_results}'
                                                 ''.format(cached_tweets=org_hashtags['cached_tweets'],
                                                           hash_tags_retrieved=org_hashtags['hash_tags_retrieved'],
                                                           unique_hashtags=org_hashtags['unique_hashtags'],
                                                           organization_link_to_hashtag_results=
                                                           org_hashtags['organization_link_to_hashtag_results']))
    return HttpResponseRedirect(reverse('organization:organization_we_vote_id_position_list',
                                        args=(organization_we_vote_id,)) +
                                "?google_civic_election_id=" + str(google_civic_election_id) + "&state_code=" +
                                str(state_code))


@login_required
def organization_retrieve_tweets_view(request, organization_we_vote_id):
    """
    For one organization, retrieve X Tweets, and capture all #Hashtags used.

    :param request:
    :param organization_we_vote_id:
    :return:
    """
    google_civic_election_id = convert_to_int(request.GET.get('google_civic_election_id', 0))
    state_code = request.GET.get('state_code', False)

    org_tweets_results = organization_retrieve_tweets_from_twitter(organization_we_vote_id)
    messages.add_message(request, messages.INFO, 'Organization retrieve tweets executed, '
                                                 'Tweets retrieved: {tweets_saved}, '
                                                 'Tweets not retrieved: {tweets_not_saved}, '
                                                 ''.format(tweets_saved=org_tweets_results['tweets_saved'],
                                                           tweets_not_saved=org_tweets_results['tweets_not_saved'],))
    return HttpResponseRedirect(reverse('organization:organization_we_vote_id_position_list',
                                        args=(organization_we_vote_id,)) +
                                "?google_civic_election_id=" + str(google_civic_election_id) + "&state_code=" +
                                str(state_code))


# This page does not need to be protected.
def organizations_sync_out_view(request):  # organizationsSyncOut
    state_served_code = request.GET.get('state_served_code', '')

    try:
        organization_queryset = Organization.objects.using('readonly').all()
        organization_queryset = organization_queryset.exclude(organization_type__iexact=INDIVIDUAL)
        if positive_value_exists(state_served_code):
            organization_queryset = organization_queryset.filter(state_served_code__iexact=state_served_code)
        organization_list_dict = organization_queryset.values(
            'we_vote_id', 'organization_name', 'organization_type',
            'organization_description', 'state_served_code',
            'organization_website', 'organization_email',
            'organization_image', 'organization_twitter_handle',
            'twitter_user_id', 'twitter_followers_count',
            'twitter_description', 'twitter_location', 'twitter_name',
            'twitter_profile_image_url_https',
            'twitter_profile_background_image_url_https',
            'twitter_profile_banner_url_https', 'organization_facebook',
            'vote_smart_id', 'organization_contact_name',
            'organization_address', 'organization_city',
            'organization_state', 'organization_zip',
            'organization_phone1', 'organization_phone2',
            'organization_fax', 'wikipedia_page_title',
            'wikipedia_page_id', 'wikipedia_photo_url',
            'wikipedia_thumbnail_url', 'wikipedia_thumbnail_width',
            'wikipedia_thumbnail_height', 'ballotpedia_page_title',
            'ballotpedia_photo_url', 'we_vote_hosted_profile_image_url_large',
            'we_vote_hosted_profile_image_url_medium', 'we_vote_hosted_profile_image_url_tiny'
        )
        if organization_list_dict:
            organization_list_json = list(organization_list_dict)
            return HttpResponse(json.dumps(organization_list_json), content_type='application/json')
    except Exception as e:
        pass

    json_data = {
        'success': False,
        'status': 'ORGANIZATION_LIST_MISSING'
    }
    return HttpResponse(json.dumps(json_data), content_type='application/json')


@login_required
def organizations_import_from_master_server_view(request):
    # admin, analytics_admin, partner_organization, political_data_manager, political_data_viewer, verified_volunteer
    authority_required = {'admin'}
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    if WE_VOTE_SERVER_ROOT_URL in ORGANIZATIONS_SYNC_URL:
        messages.add_message(request, messages.ERROR, "Cannot sync with Master We Vote Server -- "
                                                      "this is the Master We Vote Server.")
        return HttpResponseRedirect(reverse('admin_tools:admin_home', args=()))

    google_civic_election_id = convert_to_int(request.GET.get('google_civic_election_id', 0))
    state_code = request.GET.get('state_code', '')

    results = organizations_import_from_master_server(request, state_code)

    if not results['success']:
        messages.add_message(request, messages.ERROR, results['status'])
    else:
        messages.add_message(request, messages.INFO, 'Organizations import completed. '
                                                     'Saved: {saved}, Updated: {updated}, '
                                                     'Duplicates skipped: '
                                                     '{duplicates_removed}, '
                                                     'Not processed: {not_processed}'
                                                     ''.format(saved=results['saved'],
                                                               updated=results['updated'],
                                                               duplicates_removed=results['duplicates_removed'],
                                                               not_processed=results['not_processed']))
    return HttpResponseRedirect(reverse('admin_tools:sync_dashboard', args=()) + "?google_civic_election_id=" +
                                str(google_civic_election_id) + "&state_code=" + str(state_code))


@login_required
def organization_list_view(request):
    # admin, analytics_admin, partner_organization, political_data_manager, political_data_viewer, verified_volunteer
    authority_required = \
        {'partner_organization', 'political_data_manager', 'political_data_viewer', 'verified_volunteer'}
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    candidate_we_vote_id = request.GET.get('candidate_we_vote_id', '')
    google_civic_election_id = request.GET.get('google_civic_election_id', '')
    organization_search = request.GET.get('organization_search', '')
    organization_type_filter = request.GET.get('organization_type_filter', '')
    selected_issue_vote_id_list = request.GET.getlist('selected_issues', '')
    sort_by = request.GET.get('sort_by', '')
    state_code = request.GET.get('state_code', '')
    show_all = request.GET.get('show_all', False)
    show_more = request.GET.get('show_more', False)  # Show up to 1,000 organizations
    show_issues = request.GET.get('show_issues', '')

    messages_on_stage = get_messages(request)
    organization_list_query = Organization.objects.all()
    if positive_value_exists(sort_by):
        if sort_by == "twitter":
            organization_list_query = \
                organization_list_query.order_by('organization_name').order_by('-twitter_followers_count')
        else:
            organization_list_query = organization_list_query.order_by('organization_name')
    else:
        organization_list_query = organization_list_query.order_by('organization_name')

    if positive_value_exists(state_code):
        organization_list_query = organization_list_query.filter(state_served_code__iexact=state_code)

    if positive_value_exists(organization_type_filter):
        if organization_type_filter == UNKNOWN:
            # Make sure to also show organizations that are not specified
            organization_list_query = organization_list_query.filter(
                Q(organization_type__iexact=organization_type_filter) |
                Q(organization_type__isnull=True) |
                Q(organization_type__exact='')
            )
        else:
            organization_list_query = organization_list_query.filter(organization_type__iexact=organization_type_filter)
    else:
        # By default, don't show individuals
        organization_list_query = organization_list_query.exclude(organization_type__iexact=INDIVIDUAL)

    link_issue_list_manager = OrganizationLinkToIssueList()
    issue_list_manager = IssueListManager()

    # Only show organizations linked to specific issues
    # 2017-12-12 DALE I'm not sure this is being used yet...
    issues_selected = False
    issue_list = []
    if positive_value_exists(selected_issue_vote_id_list):
        issues_selected = True
        new_issue_list = []
        issue_list_manager = IssueListManager()
        issue_list_results = issue_list_manager.retrieve_issues()
        if issue_list_results["issue_list_found"]:
            issue_list = issue_list_results["issue_list"]
            for issue in issue_list:
                if issue.we_vote_id in selected_issue_vote_id_list:
                    issue.selected = True
                new_issue_list.append(issue)
            issue_list = new_issue_list

            organization_we_vote_id_list_result = link_issue_list_manager.\
                retrieve_organization_we_vote_id_list_from_issue_we_vote_id_list(selected_issue_vote_id_list)
            organization_we_vote_id_list = organization_we_vote_id_list_result['organization_we_vote_id_list']
            # we decided to not deal with case-insensitivity, in favor of using '__in'
            organization_list_query = organization_list_query.filter(we_vote_id__in=organization_we_vote_id_list)

    if positive_value_exists(organization_search):
        search_words = organization_search.split()
        for one_word in search_words:
            filters = []
            new_filter = Q(organization_name__icontains=one_word)
            filters.append(new_filter)

            new_filter = Q(organization_twitter_handle__icontains=one_word)
            filters.append(new_filter)

            new_filter = Q(organization_website__icontains=one_word)
            filters.append(new_filter)

            new_filter = Q(twitter_description__icontains=one_word)
            filters.append(new_filter)

            new_filter = Q(we_vote_id__icontains=one_word)
            filters.append(new_filter)

            new_filter = Q(vote_smart_id__icontains=one_word)
            filters.append(new_filter)

            # Add the first query
            if len(filters):
                final_filters = filters.pop()

                # ...and "OR" the remaining items in the list
                for item in filters:
                    final_filters |= item

                organization_list_query = organization_list_query.filter(final_filters)
    else:
        # This is the default organization list
        filters = []

        new_filter = Q(organization_name="")
        filters.append(new_filter)

        new_filter = Q(organization_name__startswith="Voter-")
        filters.append(new_filter)

        new_filter = Q(organization_name__startswith="wv")
        filters.append(new_filter)

        # Add the first query
        if len(filters):
            final_filters = filters.pop()

            # ...and "OR" the remaining items in the list
            for item in filters:
                final_filters |= item

            # NOTE this is "exclude"
            organization_list_query = organization_list_query.exclude(final_filters)

    organization_count = organization_list_query.count()
    messages.add_message(request, messages.INFO,
                         '{organization_count:,} organizations found.'.format(organization_count=organization_count))

    # Limit to only showing 200 on screen
    if positive_value_exists(show_more):
        organization_list = organization_list_query[:1000]
    elif positive_value_exists(show_all):
        organization_list = organization_list_query
    else:
        organization_list = organization_list_query[:200]

    # Now loop through these organizations and add on the linked_issues_count
    modified_organization_list = []
    special_interest_group_manager = VoteSmartSpecialInterestGroupManager()
    for one_organization in organization_list:
        # Turned off for now
        # one_organization.linked_issues_count = \
        #     link_issue_list_manager.fetch_issue_count_for_organization(0, one_organization.we_vote_id)
        if positive_value_exists(show_issues):
            # We want to look up the issues retrieved from Vote Smart and display them
            # if positive_value_exists(one_organization.linked_issues_count):
            show_hidden_issues = True
            one_organization.display_we_vote_issues = \
                issue_list_manager.fetch_organization_issues_for_display(
                    one_organization.we_vote_id, MOST_LINKED_ORGANIZATIONS, show_hidden_issues)
            if positive_value_exists(one_organization.vote_smart_id):
                one_organization.display_vote_smart_issues = \
                    special_interest_group_manager.fetch_vote_smart_organization_issues_for_display(
                        one_organization.vote_smart_id)
        modified_organization_list.append(one_organization)

    state_list = STATE_CODE_MAP
    sorted_state_list = sorted(state_list.items())

    organization_types_map = ORGANIZATION_TYPE_MAP
    # Sort by organization_type value (instead of key)
    organization_types_list = sorted(organization_types_map.items(), key=operator.itemgetter(1))

    template_values = {
        'messages_on_stage':        messages_on_stage,
        'candidate_we_vote_id':     candidate_we_vote_id,
        'google_civic_election_id': google_civic_election_id,
        'issue_list':               issue_list,
        'issues_selected':          issues_selected,
        'organization_type_filter': organization_type_filter,
        'organization_types':       organization_types_list,
        'organization_list':        modified_organization_list,
        'organization_search':      organization_search,
        'show_all':                 show_all,
        'show_issues':              show_issues,
        'show_more':                show_more,
        'sort_by':                  sort_by,
        'state_code':               state_code,
        'state_list':               sorted_state_list,
    }
    return render(request, 'organization/organization_list.html', template_values)


@login_required
def organization_merge_process_view(request):
    """
    Process the merging of two organizations using the Admin tool
    :param request:
    :return:
    """
    # admin, analytics_admin, partner_organization, political_data_manager, political_data_viewer, verified_volunteer
    authority_required = {'verified_volunteer'}
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    organization_manager = OrganizationManager()

    merge = request.POST.get('merge', False)
    skip = request.POST.get('skip', False)

    # Candidate 1 is the one we keep, and Candidate 2 is the one we will merge into Candidate 1
    organization1_we_vote_id = request.POST.get('organization1_we_vote_id', 0)
    organization2_we_vote_id = request.POST.get('organization2_we_vote_id', 0)
    google_civic_election_id = request.POST.get('google_civic_election_id', 0)
    redirect_to_organization_list = request.POST.get('redirect_to_organization_list', False)
    remove_duplicate_process = request.POST.get('remove_duplicate_process', False)
    state_code = request.POST.get('state_code', '')
    status = ''

    if positive_value_exists(skip):
        messages.add_message(request, messages.ERROR, 'Skip is not implemented for organizations yet.')
        # results = organization_manager.update_or_create_organizations_are_not_duplicates(
        #     organization1_we_vote_id, organization2_we_vote_id)
        # if not results['new_organizations_are_not_duplicates_created']:
        #     messages.add_message(request, messages.ERROR, 'Could not save organizations_are_not_duplicates entry: ' +
        #                          results['status'])
        # messages.add_message(request, messages.INFO, 'Prior organizations skipped, and not merged.')
        # return HttpResponseRedirect(reverse('organization:find_and_merge_duplicate_organizations', args=()) +
        #                             "?google_civic_election_id=" + str(google_civic_election_id) +
        #                             "&state_code=" + str(state_code))
        return HttpResponseRedirect(reverse('organization:compare_two_organizations_for_merge', args=()) +
                                    "?google_civic_election_id=" + str(google_civic_election_id) +
                                    "&state_code=" + str(state_code) +
                                    "&organization1_we_vote_id=" + str(organization1_we_vote_id) +
                                    "&organization2_we_vote_id=" + str(organization2_we_vote_id))

    # Check to make sure that organization2 isn't linked to a voter. If so, cancel out for now.
    voter_manager = VoterManager()
    results = voter_manager.retrieve_voter_by_organization_we_vote_id(organization2_we_vote_id, read_only=True)
    if results['voter_found']:
        status += "MERGE_PROCESS_VIEW-ORGANIZATION2_LINKED_TO_A_VOTER "
        messages.add_message(request, messages.ERROR, status)
        return HttpResponseRedirect(reverse('organization:compare_two_organizations_for_merge', args=()) +
                                    "?google_civic_election_id=" + str(google_civic_election_id) +
                                    "&state_code=" + str(state_code) +
                                    "&organization1_we_vote_id=" + str(organization1_we_vote_id) +
                                    "&organization2_we_vote_id=" + str(organization2_we_vote_id))

    # We want to check to see if organization2_we_vote_id has a TwitterLinkToOrganization entry.
    #  If it does, it means that someone has signed in with that Twitter account for that organization.
    #  As of Oct 2020 we have not set up the code to merge org2 data for voter with org1 data.
    twitter_user_manager = TwitterUserManager()
    twitter_link_to_organization_results = \
        twitter_user_manager.retrieve_twitter_link_to_organization_from_organization_we_vote_id(
            organization2_we_vote_id)
    if twitter_link_to_organization_results['twitter_link_to_organization_found']:
        messages.add_message(request, messages.ERROR, 'Organization2 has TwitterLinkToOrganization entry. '
                                                      'Merge cannot proceed.')
        return HttpResponseRedirect(reverse('organization:compare_two_organizations_for_merge', args=()) +
                                    "?google_civic_election_id=" + str(google_civic_election_id) +
                                    "&state_code=" + str(state_code) +
                                    "&organization1_we_vote_id=" + str(organization1_we_vote_id) +
                                    "&organization2_we_vote_id=" + str(organization2_we_vote_id))

    organization1_results = organization_manager.retrieve_organization_from_we_vote_id(organization1_we_vote_id)
    if organization1_results['organization_found']:
        organization1_on_stage = organization1_results['organization']
    else:
        messages.add_message(request, messages.ERROR, 'Could not retrieve organization 1.')
        return HttpResponseRedirect(reverse('organization:organization_list', args=()) +
                                    '?google_civic_election_id=' + str(google_civic_election_id) +
                                    '&state_code=' + str(state_code))

    organization2_results = organization_manager.retrieve_organization_from_we_vote_id(organization2_we_vote_id)
    if organization2_results['organization_found']:
        organization2_on_stage = organization2_results['organization']
    else:
        messages.add_message(request, messages.ERROR, 'Could not retrieve organization 2.')
        return HttpResponseRedirect(reverse('organization:organization_list', args=()) +
                                    '?google_civic_election_id=' + str(google_civic_election_id) +
                                    '&state_code=' + str(state_code))

    from_organization_id = organization2_on_stage.id
    from_organization_we_vote_id = organization2_on_stage.we_vote_id
    to_organization_id = organization1_on_stage.id
    to_organization_we_vote_id = organization1_on_stage.we_vote_id

    # Make sure we have both from_organization values
    if positive_value_exists(from_organization_id) and not positive_value_exists(from_organization_we_vote_id):
        from_organization_we_vote_id = organization_manager.fetch_we_vote_id_from_local_id(from_organization_id)
    elif positive_value_exists(from_organization_we_vote_id) and not positive_value_exists(from_organization_id):
        from_organization_id = organization_manager.fetch_organization_id(from_organization_we_vote_id)

    # Make sure we have both to_organization values
    if positive_value_exists(to_organization_id) and not positive_value_exists(to_organization_we_vote_id):
        to_organization_we_vote_id = organization_manager.fetch_we_vote_id_from_local_id(to_organization_id)
    elif positive_value_exists(to_organization_we_vote_id) and not positive_value_exists(to_organization_id):
        to_organization_id = organization_manager.fetch_organization_id(to_organization_we_vote_id)

    # If anyone is following organization2, move those followers to organization1
    move_organization_followers_results = move_organization_followers_to_another_organization(
        from_organization_id, from_organization_we_vote_id,
        to_organization_id, to_organization_we_vote_id)
    status += " " + move_organization_followers_results['status']
    if positive_value_exists(move_organization_followers_results['follow_entries_not_moved']):
        messages.add_message(request, messages.ERROR, status)
        return HttpResponseRedirect(reverse('organization:compare_two_organizations_for_merge', args=()) +
                                    "?google_civic_election_id=" + str(google_civic_election_id) +
                                    "&state_code=" + str(state_code) +
                                    "&organization1_we_vote_id=" + str(organization1_we_vote_id) +
                                    "&organization2_we_vote_id=" + str(organization2_we_vote_id))

    # If anyone has been linked with external_voter_id as a member of the old voter's organization,
    #  move those followers to the new voter's organization
    move_organization_membership_link_results = move_organization_membership_link_to_another_organization(
        from_organization_we_vote_id, to_organization_we_vote_id)
    status += " " + move_organization_membership_link_results['status']
    if positive_value_exists(move_organization_followers_results['membership_link_entries_not_moved']):
        messages.add_message(request, messages.ERROR, status)
        return HttpResponseRedirect(reverse('organization:compare_two_organizations_for_merge', args=()) +
                                    "?google_civic_election_id=" + str(google_civic_election_id) +
                                    "&state_code=" + str(state_code) +
                                    "&organization1_we_vote_id=" + str(organization1_we_vote_id) +
                                    "&organization2_we_vote_id=" + str(organization2_we_vote_id))

    # Gather choices made from merge form
    conflict_values = figure_out_organization_conflict_values(organization1_on_stage, organization2_on_stage)
    admin_merge_choices = {}
    for attribute in ORGANIZATION_UNIQUE_IDENTIFIERS:
        conflict_value = conflict_values.get(attribute, None)
        if conflict_value == "CONFLICT":
            choice = request.POST.get(attribute + '_choice', '')
            if organization2_we_vote_id == choice:
                admin_merge_choices[attribute] = getattr(organization2_on_stage, attribute)
        elif conflict_value == "CANDIDATE2":
            admin_merge_choices[attribute] = getattr(organization2_on_stage, attribute)

    merge_results = \
        merge_these_two_organizations(organization1_we_vote_id, organization2_we_vote_id, admin_merge_choices)

    if not positive_value_exists(merge_results['organizations_merged']):
        # NOTE: We could also redirect to a page to look specifically at these two organizations, but this should
        # also get you back to looking at the two organizations
        error_message = "ORGANIZATION_COMPARISON_PROBLEM: " + merge_results['status']
        messages.add_message(request, messages.ERROR, error_message)
        # return HttpResponseRedirect(reverse('organization:find_and_merge_duplicate_organizations', args=()) +
        #                             "?google_civic_election_id=" + str(google_civic_election_id) +
        #                             "&auto_merge_off=1" +
        #                             "&state_code=" + str(state_code))
        return HttpResponseRedirect(reverse('organization:organization_list', args=()) +
                                    '?google_civic_election_id=' + str(google_civic_election_id) +
                                    '&state_code=' + str(state_code))

    organization = merge_results['organization']
    messages.add_message(request, messages.INFO, "Organization '{organization_name}' merged."
                                                 "".format(organization_name=organization.organization_name))

    if redirect_to_organization_list:
        return HttpResponseRedirect(reverse('organization:organization_list', args=()) +
                                    '?google_civic_election_id=' + str(google_civic_election_id) +
                                    '&state_code=' + str(state_code))

    # if remove_duplicate_process:
    #     return HttpResponseRedirect(reverse('organization:find_and_merge_duplicate_organizations', args=()) +
    #                                 "?google_civic_election_id=" + str(google_civic_election_id) +
    #                                 "&state_code=" + str(state_code))

    return HttpResponseRedirect(reverse('organization:organization_edit', args=(organization1_on_stage.id,)))


@login_required
def organization_new_view(request):
    # admin, analytics_admin, partner_organization, political_data_manager, political_data_viewer, verified_volunteer
    authority_required = {'political_data_manager', 'verified_volunteer'}
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    # A positive value in google_civic_election_id means we want to create a voter guide for this org for this election
    google_civic_election_id = request.GET.get('google_civic_election_id', 0)

    election_manager = ElectionManager()
    upcoming_election_list = []
    results = election_manager.retrieve_upcoming_elections()
    if results['success']:
        upcoming_election_list = results['election_list']

    state_list = STATE_CODE_MAP
    sorted_state_list = sorted(state_list.items())

    messages_on_stage = get_messages(request)
    template_values = {
        'messages_on_stage':        messages_on_stage,
        'upcoming_election_list':   upcoming_election_list,
        'google_civic_election_id': google_civic_election_id,
        'state_list':               sorted_state_list,
    }
    return render(request, 'organization/organization_edit.html', template_values)


@login_required
def organization_edit_view(request, organization_id=0, organization_we_vote_id=""):
    # admin, analytics_admin, partner_organization, political_data_manager, political_data_viewer, verified_volunteer
    authority_required = {'political_data_manager', 'verified_volunteer'}
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    # A positive value in google_civic_election_id means we want to create a voter guide for this org for this election
    google_civic_election_id = request.GET.get('google_civic_election_id', 0)
    organization_type = request.GET.get('organization_type', UNKNOWN)

    messages_on_stage = get_messages(request)
    organization_id = convert_to_int(organization_id)
    organization_on_stage_found = False
    organization_manager = OrganizationManager()
    organization_on_stage = Organization()
    state_served_code = ''
    new_issue_list = []
    results = organization_manager.retrieve_organization(organization_id, organization_we_vote_id)

    if results['organization_found']:
        organization_on_stage = results['organization']
        state_served_code = organization_on_stage.state_served_code
        organization_on_stage_found = True
        issue_list_manager = IssueListManager()
        issue_list_results = issue_list_manager.retrieve_issues(ALPHABETICAL_ASCENDING, show_hidden_issues=True)
        if issue_list_results["issue_list_found"]:
            issue_list = issue_list_results["issue_list"]
            link_issue_list_manager = OrganizationLinkToIssueList()
            organization_issue_we_vote_id_list = link_issue_list_manager. \
                fetch_issue_we_vote_id_list_by_organization_we_vote_id(organization_on_stage.we_vote_id)

            for issue in issue_list:
                if issue.we_vote_id in organization_issue_we_vote_id_list:
                    issue.followed_by_organization = True
                else:
                    issue.followed_by_organization = False
                new_issue_list.append(issue)

    election_manager = ElectionManager()
    upcoming_election_list = []
    results = election_manager.retrieve_upcoming_elections()
    if results['success']:
        upcoming_election_list = results['election_list']

    state_list = STATE_CODE_MAP
    sorted_state_list = sorted(state_list.items())

    organization_types_map = ORGANIZATION_TYPE_MAP
    # Sort by organization_type value (instead of key)
    organization_types_list = sorted(organization_types_map.items(), key=operator.itemgetter(1))

    if organization_on_stage_found:
        template_values = {
            'messages_on_stage':        messages_on_stage,
            'organization':             organization_on_stage,
            'organization_types':       organization_types_list,
            'upcoming_election_list':   upcoming_election_list,
            'google_civic_election_id': google_civic_election_id,
            'state_list':               sorted_state_list,
            'state_served_code':        state_served_code,
            'issue_list':               new_issue_list,
        }
    else:
        template_values = {
            'messages_on_stage':        messages_on_stage,
            'upcoming_election_list':   upcoming_election_list,
            'google_civic_election_id': google_civic_election_id,
            'state_list':               sorted_state_list,
            'issue_list':               new_issue_list,
        }
    return render(request, 'organization/organization_edit.html', template_values)


@login_required
def organization_edit_account_view(request, organization_id=0, organization_we_vote_id=""):
    # admin, analytics_admin, partner_organization, political_data_manager, political_data_viewer, verified_volunteer
    authority_required = {'political_data_manager', 'verified_volunteer'}
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    # A positive value in google_civic_election_id means we want to create a voter guide for this org for this election
    google_civic_election_id = request.GET.get('google_civic_election_id', 0)
    organization_type = request.GET.get('organization_type', UNKNOWN)

    messages_on_stage = get_messages(request)
    organization_id = convert_to_int(organization_id)
    organization_on_stage_found = False
    organization_manager = OrganizationManager()
    organization_on_stage = Organization()
    state_served_code = ''
    new_issue_list = []
    results = organization_manager.retrieve_organization(organization_id, organization_we_vote_id)

    if results['organization_found']:
        organization_on_stage = results['organization']
        state_served_code = organization_on_stage.state_served_code
        organization_on_stage_found = True
        issue_list_manager = IssueListManager()
        issue_list_results = issue_list_manager.retrieve_issues(ALPHABETICAL_ASCENDING, show_hidden_issues=True)
        if issue_list_results["issue_list_found"]:
            issue_list = issue_list_results["issue_list"]
            link_issue_list_manager = OrganizationLinkToIssueList()
            organization_issue_we_vote_id_list = link_issue_list_manager. \
                fetch_issue_we_vote_id_list_by_organization_we_vote_id(organization_on_stage.we_vote_id)

            for issue in issue_list:
                if issue.we_vote_id in organization_issue_we_vote_id_list:
                    issue.followed_by_organization = True
                else:
                    issue.followed_by_organization = False
                new_issue_list.append(issue)

    election_manager = ElectionManager()
    upcoming_election_list = []
    results = election_manager.retrieve_upcoming_elections()
    if results['success']:
        upcoming_election_list = results['election_list']

    state_list = STATE_CODE_MAP
    sorted_state_list = sorted(state_list.items())

    master_feature_package_query = MasterFeaturePackage.objects.all()
    master_feature_package_list = list(master_feature_package_query)

    organization_types_map = ORGANIZATION_TYPE_MAP
    # Sort by organization_type value (instead of key)
    organization_types_list = sorted(organization_types_map.items(), key=operator.itemgetter(1))

    if organization_on_stage_found:
        template_values = {
            'google_civic_election_id': google_civic_election_id,
            'issue_list':               new_issue_list,
            'master_feature_package_list': master_feature_package_list,
            'messages_on_stage':        messages_on_stage,
            'organization':             organization_on_stage,
            'organization_types':       organization_types_list,
            'state_list':               sorted_state_list,
            'state_served_code':        state_served_code,
            'upcoming_election_list':   upcoming_election_list,
        }
    else:
        template_values = {
            'google_civic_election_id': google_civic_election_id,
            'issue_list':               new_issue_list,
            'master_feature_package_list': master_feature_package_list,
            'messages_on_stage':        messages_on_stage,
            'state_list':               sorted_state_list,
            'upcoming_election_list':   upcoming_election_list,
        }
    return render(request, 'organization/organization_edit_account.html', template_values)


@login_required
def organization_delete_process_view(request):
    """
    Delete an organization
    :param request:
    :return:
    """
    status = ""
    organization_id = convert_to_int(request.POST.get('organization_id', 0))
    confirm_delete = convert_to_int(request.POST.get('confirm_delete', 0))

    google_civic_election_id = request.POST.get('google_civic_election_id', 0)
    state_code = request.POST.get('state_code', '')

    # admin, analytics_admin, partner_organization, political_data_manager, political_data_viewer, verified_volunteer
    authority_required = {'political_data_manager', 'admin'}
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    if not positive_value_exists(confirm_delete):
        messages.add_message(request, messages.ERROR,
                             'Unable to delete this organization. '
                             'Please check the checkbox to confirm you want to delete this organization.')
        return HttpResponseRedirect(reverse('organization:organization_edit', args=(organization_id,)) +
                                    "?google_civic_election_id=" + str(google_civic_election_id) +
                                    "&state_code=" + str(state_code))

    organization_manager = OrganizationManager()
    results = organization_manager.retrieve_organization(organization_id)
    if results['organization_found']:
        organization = results['organization']

        organization_link_to_issue_list = OrganizationLinkToIssueList()
        issue_count = organization_link_to_issue_list.fetch_issue_count_for_organization(0, organization.we_vote_id)

        if positive_value_exists(issue_count):
            messages.add_message(request, messages.ERROR, 'Could not delete -- '
                                                          'issues still attached to this organization.')
            return HttpResponseRedirect(reverse('organization:organization_edit', args=(organization_id,)) +
                                        "?google_civic_election_id=" + str(google_civic_election_id) +
                                        "&state_code=" + str(state_code))

        organization_we_vote_id = organization.we_vote_id

        # Delete the TwitterLinkToOrganization
        twitter_user_manager = TwitterUserManager()
        twitter_id = 0
        results = twitter_user_manager.delete_twitter_link_to_organization(twitter_id, organization_we_vote_id)
        if not positive_value_exists(results['twitter_link_to_organization_deleted']) \
                and not positive_value_exists(results['twitter_link_to_organization_not_found']):
            status += results['status']
            messages.add_message(request, messages.ERROR, 'Could not delete TwitterLinkToOrganization: {status}'
                                                          ''.format(status=status))
            return HttpResponseRedirect(reverse('organization:organization_edit', args=(organization_id,)) +
                                        "?google_civic_election_id=" + str(google_civic_election_id) +
                                        "&state_code=" + str(state_code))

        organization.delete()
        messages.add_message(request, messages.INFO, 'Organization deleted.')
    else:
        messages.add_message(request, messages.ERROR, 'Organization not found.')

    return HttpResponseRedirect(reverse('organization:organization_list', args=()))


@login_required
def organization_edit_process_view(request):
    """
    Process the new or edit organization forms
    :param request:
    :return:
    """
    # admin, analytics_admin, partner_organization, political_data_manager, political_data_viewer, verified_volunteer
    authority_required = {'political_data_manager', 'verified_volunteer'}
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    issue_analysis_admin_notes = request.POST.get('issue_analysis_admin_notes', False)
    issue_analysis_done = request.POST.get('issue_analysis_done', False)
    organization_endorsements_api_url = request.POST.get('organization_endorsements_api_url', False)
    organization_id = convert_to_int(request.POST.get('organization_id', 0))
    organization_link_issue_we_vote_ids = request.POST.getlist('selected_issues', False)
    organization_name = request.POST.get('organization_name', '')
    organization_twitter_handle = request.POST.get('organization_twitter_handle', False)
    organization_email = request.POST.get('organization_email', False)
    organization_facebook = request.POST.get('organization_facebook', False)
    organization_type = request.POST.get('organization_type', GROUP)
    organization_website = request.POST.get('organization_website', False)
    state_served_code = request.POST.get('state_served_code', False)
    wikipedia_page_title = request.POST.get('wikipedia_page_title', False)
    wikipedia_photo_url = request.POST.get('wikipedia_photo_url', False)

    # A positive value in google_civic_election_id or add_organization_button means we want to create a voter guide
    # for this org for this election
    google_civic_election_id = request.POST.get('google_civic_election_id', 0)
    election_manager = ElectionManager()
    current_organization_with_new_twitter_handle = False

    # Have a version of state_code that is "" instead of False
    if positive_value_exists(state_served_code):
        state_code = state_served_code
    else:
        state_code = ""

    # Filter incoming data
    organization_twitter_handle = extract_twitter_handle_from_text_string(organization_twitter_handle)

    # Check to see if this organization is already being used anywhere
    organization_on_stage_found = False
    new_organization_created = False
    status = ""
    try:
        organization_query = Organization.objects.filter(id=organization_id)
        if organization_query.count():
            organization_on_stage = organization_query[0]
            organization_on_stage_found = True
    except Exception as e:
        handle_record_not_found_exception(e, logger=logger)

    try:
        if organization_on_stage_found:
            # Update
            if positive_value_exists(organization_on_stage.organization_twitter_handle):
                if positive_value_exists(organization_twitter_handle):
                    if organization_on_stage.organization_twitter_handle != organization_twitter_handle:
                        # Twitter handle has changed
                        current_organization_with_new_twitter_handle = True
            else:
                if positive_value_exists(organization_twitter_handle):
                    # Twitter handle added where before there wasn't one
                    current_organization_with_new_twitter_handle = True

            if issue_analysis_admin_notes is not False:
                organization_on_stage.issue_analysis_admin_notes = issue_analysis_admin_notes.strip()
            if issue_analysis_done is not False:
                organization_on_stage.issue_analysis_done = issue_analysis_done
            if organization_name is not False:
                organization_on_stage.organization_name = organization_name.strip()
            if organization_twitter_handle is not False:
                organization_on_stage.organization_twitter_handle = organization_twitter_handle.strip()
            if organization_email is not False:
                organization_on_stage.organization_email = organization_email.strip()
            if organization_facebook is not False:
                organization_on_stage.organization_facebook = organization_facebook.strip()
            if organization_website is not False:
                organization_on_stage.organization_website = organization_website.strip()
            if wikipedia_page_title is not False:
                organization_on_stage.wikipedia_page_title = wikipedia_page_title.strip()
            if wikipedia_photo_url is not False:
                organization_on_stage.wikipedia_photo_url = wikipedia_photo_url.strip()
            if organization_endorsements_api_url is not False:
                organization_on_stage.organization_endorsements_api_url = organization_endorsements_api_url.strip()
            if state_served_code is not False:
                organization_on_stage.state_served_code = state_served_code.strip()
            if organization_type is not False:
                organization_on_stage.organization_type = organization_type.strip()
            organization_on_stage.save()
            organization_id = organization_on_stage.id
            organization_we_vote_id = organization_on_stage.we_vote_id

            messages.add_message(request, messages.INFO, 'Organization updated.')
        else:
            # Create new

            # But first double-check that we don't have an org entry already
            organization_email = ''
            organization_list_manager = OrganizationListManager()
            results = organization_list_manager.organization_search_find_any_possibilities(
                organization_name, organization_twitter_handle, organization_website, organization_email)

            if results['organizations_found']:
                organizations_list = results['organizations_list']
                organizations_count = len(organizations_list)

                upcoming_election_list = []
                results = election_manager.retrieve_upcoming_elections()
                if results['success']:
                    upcoming_election_list = results['election_list']

                state_list = STATE_CODE_MAP
                sorted_state_list = sorted(state_list.items())

                messages.add_message(request, messages.INFO, 'We found {count} existing organizations '
                                                             'that might match.'.format(count=organizations_count))
                messages_on_stage = get_messages(request)
                template_values = {
                    'google_civic_election_id':     google_civic_election_id,
                    'messages_on_stage':            messages_on_stage,
                    'organizations_list':           organizations_list,
                    'organization_name':            organization_name,
                    'organization_twitter_handle':  organization_twitter_handle,
                    'organization_facebook':        organization_facebook,
                    'organization_website':         organization_website,
                    'wikipedia_page_title':         wikipedia_page_title,
                    'wikipedia_photo_url':          wikipedia_photo_url,
                    'state_served_code':            state_served_code,
                    'state_list':                   sorted_state_list,
                    'upcoming_election_list':       upcoming_election_list,
                }
                return render(request, 'voter_guide/voter_guide_search.html', template_values)

            minimum_required_variables_exist = positive_value_exists(organization_name)
            if not minimum_required_variables_exist:
                upcoming_election_list = []
                results = election_manager.retrieve_upcoming_elections()
                if results['success']:
                    upcoming_election_list = results['election_list']

                state_list = STATE_CODE_MAP
                sorted_state_list = sorted(state_list.items())

                messages.add_message(request, messages.INFO, 'Missing name, which is required.')
                messages_on_stage = get_messages(request)
                template_values = {
                    'google_civic_election_id':     google_civic_election_id,
                    'messages_on_stage':            messages_on_stage,
                    'organization_name':            organization_name,
                    'organization_twitter_handle':  organization_twitter_handle,
                    'organization_facebook':        organization_facebook,
                    'organization_website':         organization_website,
                    'wikipedia_page_title':         wikipedia_page_title,
                    'wikipedia_photo_url':          wikipedia_photo_url,
                    'state_served_code':            state_served_code,
                    'state_list':                   sorted_state_list,
                    'upcoming_election_list':       upcoming_election_list,
                }
                return render(request, 'voter_guide/voter_guide_search.html', template_values)

            organization_on_stage = Organization(
                organization_name=organization_name,
            )
            if issue_analysis_admin_notes is not False:
                organization_on_stage.issue_analysis_admin_notes = issue_analysis_admin_notes
            if issue_analysis_done is not False:
                organization_on_stage.issue_analysis_done = issue_analysis_done
            if organization_twitter_handle is not False:
                organization_on_stage.organization_twitter_handle = organization_twitter_handle
            if organization_email is not False:
                organization_on_stage.organization_email = organization_email
            if organization_facebook is not False:
                organization_on_stage.organization_facebook = organization_facebook
            if organization_website is not False:
                organization_on_stage.organization_website = organization_website
            if wikipedia_page_title is not False:
                organization_on_stage.wikipedia_page_title = wikipedia_page_title
            if wikipedia_photo_url is not False:
                organization_on_stage.wikipedia_photo_url = wikipedia_photo_url
            if organization_endorsements_api_url is not False:
                organization_on_stage.organization_endorsements_api_url = organization_endorsements_api_url
            if state_served_code is not False:
                organization_on_stage.state_served_code = state_served_code
            if organization_type is not False:
                organization_on_stage.organization_type = organization_type
            organization_on_stage.save()
            organization_id = organization_on_stage.id
            organization_we_vote_id = organization_on_stage.we_vote_id
            messages.add_message(request, messages.INFO, 'New organization saved.')
            new_organization_created = True
    except Exception as e:
        messages.add_message(request, messages.ERROR, 'Could not save organization.'
                                                      ' {error} [type: {error_type}]'.format(error=e,
                                                                                             error_type=type(e)))
        return HttpResponseRedirect(reverse('organization:organization_list', args=()))

    new_organization_and_new_twitter_handle = positive_value_exists(new_organization_created) \
        and positive_value_exists(organization_we_vote_id) \
        and positive_value_exists(organization_twitter_handle)
    # Update Twitter information
    if new_organization_and_new_twitter_handle or current_organization_with_new_twitter_handle:
        # Pull Twitter information
        results = refresh_twitter_organization_details(organization_on_stage)
        status += results['status']
        organization_on_stage = results['organization']
        twitter_user_id = results['twitter_user_id']

        if positive_value_exists(twitter_user_id):
            # Try to link Twitter to this organization. If already linked, this function will fail because of
            # database unique field requirements.
            twitter_user_manager = TwitterUserManager()
            results = twitter_user_manager.create_twitter_link_to_organization(twitter_user_id, organization_we_vote_id)

    if positive_value_exists(organization_we_vote_id):
        push_organization_data_to_other_table_caches(organization_we_vote_id)

    # Voter guide names are currently locked to the organization name, so we want to update all voter guides
    voter_guide_manager = VoterGuideManager()
    results = voter_guide_manager.update_organization_voter_guides_with_organization_data(organization_on_stage)

    # Create voter_guide for this election?
    if positive_value_exists(google_civic_election_id) and positive_value_exists(organization_we_vote_id):
        election_manager = ElectionManager()
        results = election_manager.retrieve_election(google_civic_election_id)
        if results['election_found']:
            election = results['election']

            voter_guide_we_vote_id = ''
            results = voter_guide_manager.update_or_create_organization_voter_guide_by_election_id(
                voter_guide_we_vote_id, organization_we_vote_id, google_civic_election_id, state_code)
            if results['voter_guide_saved']:
                messages.add_message(request, messages.INFO, 'Voter guide for {election_name} election saved.'
                                                             ''.format(election_name=election.election_name))

    # Link the selected issues with organization and delete any links that were unselected
    link_issue_list_manager = OrganizationLinkToIssueList()
    link_issue_manager = OrganizationLinkToIssueManager()
    issue_id = 0

    organization_follow_issues_we_vote_id_list_prior_to_update = link_issue_list_manager.\
        fetch_issue_we_vote_id_list_by_organization_we_vote_id(organization_we_vote_id)

    if positive_value_exists(organization_link_issue_we_vote_ids):
        # If here we have a complete list of issues that the organization should be linked to
        for issue_we_vote_id in organization_link_issue_we_vote_ids:
            if issue_we_vote_id in organization_follow_issues_we_vote_id_list_prior_to_update:
                organization_follow_issues_we_vote_id_list_prior_to_update.remove(issue_we_vote_id)
            else:
                # If here, this is a new issue link
                link_issue_manager.link_organization_to_issue(organization_we_vote_id, issue_id, issue_we_vote_id)
    # this check necessary when, organization has issues linked previously, but all the
    # issues are unchecked
    if positive_value_exists(organization_follow_issues_we_vote_id_list_prior_to_update):
        # If a previously linked issue was NOT on the complete list of issues taken in above, unlink those issues
        for issue_we_vote_id in organization_follow_issues_we_vote_id_list_prior_to_update:
            link_issue_manager.unlink_organization_to_issue(organization_we_vote_id, issue_id, issue_we_vote_id)

    position_list_manager = PositionListManager()
    position_list_manager.refresh_cached_position_info_for_organization(organization_we_vote_id)

    return HttpResponseRedirect(reverse('organization:organization_position_list', args=(organization_id,)) +
                                "?google_civic_election_id=" + str(google_civic_election_id) + "&state_code=" +
                                str(state_code))


@login_required
def organization_edit_account_process_view(request):
    """
    Process the edit organization account forms
    :param request:
    :return:
    """
    # admin, analytics_admin, partner_organization, political_data_manager, political_data_viewer, verified_volunteer
    authority_required = {'political_data_manager'}
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    organization_id = convert_to_int(request.POST.get('organization_id', 0))
    chosen_domain_string = request.POST.get('chosen_domain_string', None)
    chosen_favicon_url_https = request.POST.get('chosen_favicon_url_https', None)
    chosen_google_analytics_account_number = request.POST.get('chosen_google_analytics_account_number', None)
    chosen_html_verification_string = request.POST.get('chosen_html_verification_string', None)
    chosen_hide_we_vote_logo = request.POST.get('chosen_hide_we_vote_logo', None)
    chosen_logo_url_https = request.POST.get('chosen_logo_url_https', None)
    chosen_organization_api_pass_code = request.POST.get('chosen_organization_api_pass_code', None)
    chosen_prevent_sharing_opinions = request.POST.get('chosen_prevent_sharing_opinions', None)
    chosen_ready_introduction_text = request.POST.get('chosen_ready_introduction_text', None)
    chosen_ready_introduction_title = request.POST.get('chosen_ready_introduction_title', None)
    chosen_social_share_description = request.POST.get('chosen_social_share_description', None)
    chosen_social_share_image_256x256_url_https = request.POST.get('chosen_social_share_image_256x256_url_https', None)
    chosen_subdomain_string = request.POST.get('chosen_subdomain_string', None)
    chosen_feature_package = request.POST.get('chosen_feature_package', None)
    google_civic_election_id = request.POST.get('google_civic_election_id', 0)
    state_code = request.POST.get('state_code', None)

    # Check to see if this organization is already being used anywhere
    organization_on_stage = None
    organization_on_stage_found = False
    status = ""
    try:
        organization_on_stage = Organization.objects.get(id=organization_id)
        organization_on_stage_found = True
    except Exception as e:
        messages.add_message(request, messages.ERROR, 'Account settings can only be edited on existing organization.')
        status += "EDIT_ACCOUNT_PROCESS_ORGANIZATION_NOT_FOUND "

    try:
        if organization_on_stage_found:
            # Update
            if chosen_domain_string is not None:
                if positive_value_exists(chosen_domain_string):
                    domain_results = full_domain_string_available(chosen_domain_string,
                                                                  requesting_organization_id=organization_id)
                    if domain_results['full_domain_string_available']:
                        organization_on_stage.chosen_domain_string = chosen_domain_string.strip()
                    else:
                        message = 'Cannot save full domain: \'' + chosen_domain_string + '\', status: ' + \
                                  domain_results['status']
                        messages.add_message(request, messages.ERROR, message)
                        status += domain_results['status']
                else:
                    organization_on_stage.chosen_domain_string = None
            if chosen_favicon_url_https is not None:
                organization_on_stage.chosen_favicon_url_https = chosen_favicon_url_https
            if chosen_google_analytics_account_number is not None:
                organization_on_stage.chosen_google_analytics_account_number = \
                    chosen_google_analytics_account_number.strip()
            if chosen_html_verification_string is not None:
                organization_on_stage.chosen_html_verification_string = chosen_html_verification_string.strip()
            if chosen_hide_we_vote_logo is not None:
                organization_on_stage.chosen_hide_we_vote_logo = positive_value_exists(chosen_hide_we_vote_logo)
            if chosen_logo_url_https is not None:
                organization_on_stage.chosen_logo_url_https = chosen_logo_url_https.strip()
            if chosen_organization_api_pass_code is not None:
                organization_on_stage.chosen_organization_api_pass_code = chosen_organization_api_pass_code.strip()
            if chosen_prevent_sharing_opinions is not None:
                organization_on_stage.chosen_prevent_sharing_opinions \
                    = positive_value_exists(chosen_prevent_sharing_opinions)
            if chosen_ready_introduction_text is not None:
                organization_on_stage.chosen_ready_introduction_text = chosen_ready_introduction_text
            if chosen_ready_introduction_title is not None:
                organization_on_stage.chosen_ready_introduction_title = chosen_ready_introduction_title
            if chosen_social_share_description is not None:
                organization_on_stage.chosen_social_share_description = chosen_social_share_description.strip()
            if chosen_social_share_image_256x256_url_https is not None:
                organization_on_stage.chosen_social_share_image_256x256_url_https = \
                    chosen_social_share_image_256x256_url_https.strip()
            if chosen_subdomain_string is not None:
                if positive_value_exists(chosen_subdomain_string):
                    domain_results = subdomain_string_available(chosen_subdomain_string,
                                                                requesting_organization_id=organization_id)
                    if domain_results['subdomain_string_available']:
                        organization_on_stage.chosen_subdomain_string = chosen_subdomain_string.strip()
                    else:
                        message = 'Cannot save sub domain: \'' + chosen_subdomain_string + '\', status: ' + \
                                  domain_results['status']
                        messages.add_message(request, messages.ERROR, message)
                        status += domain_results['status']
                else:
                    organization_on_stage.chosen_subdomain_string = None
            if chosen_feature_package is not None:
                master_feature_package_query = MasterFeaturePackage.objects.all()
                master_feature_package_list = list(master_feature_package_query)
                for feature_package in master_feature_package_list:
                    if feature_package.master_feature_package == chosen_feature_package:
                        organization_on_stage.chosen_feature_package = chosen_feature_package
                        organization_on_stage.features_provided_bitmap = feature_package.features_provided_bitmap

            organization_on_stage.save()
            organization_id = organization_on_stage.id

            messages.add_message(request, messages.INFO, 'Organization account information updated.')
        else:
            # We do not create organizations in this view
            pass
    except Exception as e:
        messages.add_message(request, messages.ERROR, 'Could not save organization.'
                                                      ' {error} [type: {error_type}]'.format(error=e,
                                                                                             error_type=type(e)))

    return HttpResponseRedirect(reverse('organization:organization_position_list', args=(organization_id,)) +
                                "?google_civic_election_id=" + str(google_civic_election_id) +
                                "&state_code=" + str(state_code))


@login_required
def organization_position_list_view(request, organization_id=0, organization_we_vote_id="", incorrect_integer=0):
    # admin, analytics_admin, partner_organization, political_data_manager, political_data_viewer, verified_volunteer
    authority_required = \
        {'partner_organization', 'political_data_manager', 'political_data_viewer', 'verified_volunteer'}
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    status = ""
    messages_on_stage = get_messages(request)
    organization_id = convert_to_int(organization_id)
    organization_search_for_merge = request.GET.get('organization_search_for_merge', "")
    google_civic_election_id = convert_to_int(request.GET.get('google_civic_election_id', 0))
    candidate_campaign_id = request.GET.get('candidate_campaign_id', 0)
    candidate_we_vote_id = request.GET.get('candidate_we_vote_id', '')
    show_all_elections = positive_value_exists(request.GET.get('show_all_elections', False))

    election_manager = ElectionManager()
    if positive_value_exists(show_all_elections):
        results = election_manager.retrieve_elections()
        election_list = results['election_list']
    else:
        results = election_manager.retrieve_upcoming_elections()
        election_list = results['election_list']
        # Make sure we always include the current election in the election_list, even if it is older
        if positive_value_exists(google_civic_election_id):
            this_election_found = False
            for one_election in election_list:
                if convert_to_int(one_election.google_civic_election_id) == convert_to_int(google_civic_election_id):
                    this_election_found = True
                    break
            if not this_election_found:
                results = election_manager.retrieve_election(google_civic_election_id)
                if results['election_found']:
                    one_election = results['election']
                    election_list.append(one_election)

    google_civic_election_id_list = []
    for one_election in election_list:
        google_civic_election_id_list.append(str(one_election.google_civic_election_id))

    # We pass candidate_we_vote_id to this page to pre-populate the form
    candidate_campaign_manager = CandidateCampaignManager()
    if positive_value_exists(candidate_we_vote_id):
        candidate_campaign_id = 0
        results = candidate_campaign_manager.retrieve_candidate_campaign_from_we_vote_id(candidate_we_vote_id)
        if results['candidate_campaign_found']:
            candidate_campaign = results['candidate_campaign']
            candidate_campaign_id = candidate_campaign.id
    elif positive_value_exists(candidate_campaign_id):
        pass

    organization_on_stage = Organization()
    organization_on_stage_found = False
    organization_issues_list = []
    organization_blocked_issues_list = []
    try:
        if positive_value_exists(organization_id):
            organization_query = Organization.objects.filter(id=organization_id)
        else:
            organization_query = Organization.objects.filter(we_vote_id__iexact=organization_we_vote_id)
        if organization_query.count():
            organization_on_stage = organization_query[0]
            organization_on_stage_found = True
            organization_we_vote_id = organization_on_stage.we_vote_id
            organization_id = organization_on_stage.id
    except Exception as e:
        handle_record_not_found_exception(e, logger=logger)
        organization_on_stage_found = False

    candidate_list_manager = CandidateCampaignListManager()
    if not organization_on_stage_found:
        messages.add_message(request, messages.ERROR,
                             'Could not find organization when trying to retrieve positions.')
        return HttpResponseRedirect(reverse('organization:organization_list', args=()))

    results = candidate_list_manager.retrieve_candidate_we_vote_id_list_from_election_list(
        google_civic_election_id_list)
    if not positive_value_exists(results['success']):
        status += results['status']
    candidate_we_vote_id_list = results['candidate_we_vote_id_list']

    try:
        public_position_query = PositionEntered.objects.all()
        # As of Aug 2018 we are no longer using PERCENT_RATING
        public_position_query = public_position_query.exclude(stance__iexact='PERCENT_RATING')
        public_position_query = public_position_query.filter(organization_id=organization_id)
        if positive_value_exists(google_civic_election_id):
            public_position_query = public_position_query\
                .filter(Q(google_civic_election_id=google_civic_election_id) |
                        Q(candidate_campaign_we_vote_id__in=candidate_we_vote_id_list))
        elif len(google_civic_election_id_list):
            public_position_query = public_position_query\
                .filter(Q(google_civic_election_id__in=google_civic_election_id_list) |
                        Q(candidate_campaign_we_vote_id__in=candidate_we_vote_id_list))
        public_position_query = public_position_query.order_by('-id')
        public_position_list = list(public_position_query)

        friends_only_position_query = PositionForFriends.objects.all()
        # As of Aug 2018 we are no longer using PERCENT_RATING
        friends_only_position_query = friends_only_position_query.exclude(stance__iexact='PERCENT_RATING')
        friends_only_position_query = friends_only_position_query.filter(organization_id=organization_id)
        if positive_value_exists(google_civic_election_id):
            friends_only_position_query = friends_only_position_query\
                .filter(Q(google_civic_election_id=google_civic_election_id) |
                        Q(candidate_campaign_we_vote_id__in=candidate_we_vote_id_list))
        elif len(google_civic_election_id_list):
            friends_only_position_query = friends_only_position_query\
                .filter(Q(google_civic_election_id__in=google_civic_election_id_list) |
                        Q(candidate_campaign_we_vote_id__in=candidate_we_vote_id_list))
        friends_only_position_query = friends_only_position_query.order_by('-id')
        friends_only_position_list = list(friends_only_position_query)

        organization_position_list = public_position_list + friends_only_position_list
        if len(public_position_list) or len(friends_only_position_list):
            organization_position_list_found = True

        link_issue_list_manager = OrganizationLinkToIssueList()
        organization_link_issue_list = link_issue_list_manager. \
            retrieve_issue_list_by_organization_we_vote_id(organization_we_vote_id)
        issue_manager = IssueManager()
        for link_issue in organization_link_issue_list:
            issue_object = issue_manager.fetch_issue_from_we_vote_id(link_issue.issue_we_vote_id)
            organization_issues_list.append(issue_object)

        organization_link_block_issue_list = link_issue_list_manager.\
            retrieve_issue_blocked_list_by_organization_we_vote_id(organization_we_vote_id)
        for blocked_issue in organization_link_block_issue_list:
            issue_object = issue_manager.fetch_issue_from_we_vote_id(blocked_issue.issue_we_vote_id)
            organization_blocked_issues_list.append(issue_object)

    except Exception as e:
        status += "COULD_NOT_RETRIEVE_POSITION_LIST " + str(e) + ' '
        organization_position_list = []

    voter_manager = VoterManager()
    voter_results = voter_manager.retrieve_voter_by_organization_we_vote_id(organization_we_vote_id)
    if voter_results['voter_found']:
        voter = voter_results['voter']
    else:
        voter = None

    offices_dict = {}
    candidates_dict = {}
    measures_dict = {}
    organizations_dict = {}
    voters_by_linked_org_dict = {}
    voters_dict = {}
    for one_position in organization_position_list:
        position_manager = PositionManager()
        results = position_manager.refresh_cached_position_info(
            one_position, offices_dict=offices_dict, candidates_dict=candidates_dict, measures_dict=measures_dict,
            organizations_dict=organizations_dict, voters_by_linked_org_dict=voters_by_linked_org_dict,
            voters_dict=voters_dict)
        offices_dict = results['offices_dict']
        candidates_dict = results['candidates_dict']
        measures_dict = results['measures_dict']
        organizations_dict = results['organizations_dict']
        voters_by_linked_org_dict = results['voters_by_linked_org_dict']
        voters_dict = results['voters_dict']

    organization_search_results_list = []
    if positive_value_exists(organization_search_for_merge) and positive_value_exists(organization_we_vote_id):
        organization_query = Organization.objects.all()
        organization_query = organization_query.exclude(we_vote_id__iexact=organization_we_vote_id)

        search_words = organization_search_for_merge.split()
        for one_word in search_words:
            filters = []  # Reset for each search word
            new_filter = Q(organization_name__icontains=one_word)
            filters.append(new_filter)

            new_filter = Q(we_vote_id__iexact=one_word)
            filters.append(new_filter)

            new_filter = Q(organization_description__icontains=one_word)
            filters.append(new_filter)

            new_filter = Q(organization_twitter_handle__icontains=one_word)
            filters.append(new_filter)

            new_filter = Q(organization_instagram_handle__icontains=one_word)
            filters.append(new_filter)

            # Add the first query
            if len(filters):
                final_filters = filters.pop()

                # ...and "OR" the remaining items in the list
                for item in filters:
                    final_filters |= item

                organization_query = organization_query.filter(final_filters)

        organization_search_results_list = list(organization_query)

    organization_type_display_text = ORGANIZATION_TYPE_MAP.get(organization_on_stage.organization_type,
                                                               ORGANIZATION_TYPE_MAP[UNKNOWN])
    template_values = {
        'messages_on_stage':                messages_on_stage,
        'organization':                     organization_on_stage,
        'organization_position_list':       organization_position_list,
        'organization_num_positions':       len(organization_position_list),
        'organization_search_for_merge':    organization_search_for_merge,
        'organization_search_results_list': organization_search_results_list,
        'organization_type_display_text':   organization_type_display_text,
        'election_list':                    election_list,
        'google_civic_election_id':         google_civic_election_id,
        'candidate_campaign_id':            candidate_campaign_id,
        'candidate_we_vote_id':             candidate_we_vote_id,
        'show_all_elections':               show_all_elections,
        'voter':                            voter,
        'organization_issues_list':         organization_issues_list,
        'organization_blocked_issues_list': organization_blocked_issues_list,
    }
    return render(request, 'organization/organization_position_list.html', template_values)


@login_required
def organization_position_new_view(request, organization_id):
    # admin, analytics_admin, partner_organization, political_data_manager, political_data_viewer, verified_volunteer
    authority_required = {'political_data_manager', 'verified_volunteer'}
    authority_results = retrieve_voter_authority(request)
    if not voter_has_authority(request, authority_required, authority_results):
        return redirect_to_sign_in_page(request, authority_required)

    google_civic_election_id = request.GET.get('google_civic_election_id', 0)
    candidate_campaign_id = request.GET.get('candidate_campaign_id', 0)
    candidate_we_vote_id = request.GET.get('candidate_we_vote_id', False)
    measure_we_vote_id = request.GET.get('measure_we_vote_id', False)
    state_code = request.GET.get('state_code', '')
    show_all_elections = positive_value_exists(request.GET.get('show_all_elections', False))

    # Take in some incoming values
    candidate_and_measure_not_found = request.GET.get('candidate_and_measure_not_found', False)
    stance = request.GET.get('stance', SUPPORT)  # Set a default if stance comes in empty
    statement_text = request.GET.get('statement_text', '')  # Set a default if stance comes in empty
    more_info_url = request.GET.get('more_info_url', '')

    # We pass candidate_we_vote_id to this page to pre-populate the form
    candidate_campaign_manager = CandidateCampaignManager()
    if positive_value_exists(candidate_we_vote_id):
        candidate_campaign_id = 0
        results = candidate_campaign_manager.retrieve_candidate_campaign_from_we_vote_id(candidate_we_vote_id)
        if results['candidate_campaign_found']:
            candidate_campaign = results['candidate_campaign']
            candidate_campaign_id = candidate_campaign.id
    elif positive_value_exists(candidate_campaign_id):
        pass

    # We pass candidate_we_vote_id to this page to pre-populate the form
    contest_measure_id = 0
    if positive_value_exists(measure_we_vote_id):
        contest_measure_manager = ContestMeasureManager()
        results = contest_measure_manager.retrieve_contest_measure_from_we_vote_id(measure_we_vote_id)
        if results['contest_measure_found']:
            contest_measure = results['contest_measure']
            contest_measure_id = contest_measure.id

    messages_on_stage = get_messages(request)
    organization_id = convert_to_int(organization_id)
    all_is_well = True
    organization_on_stage_found = False
    organization_on_stage = Organization()
    try:
        organization_on_stage = Organization.objects.get(id=organization_id)
        organization_on_stage_found = True
    except Organization.MultipleObjectsReturned as e:
        handle_record_found_more_than_one_exception(e, logger=logger)
    except Organization.DoesNotExist:
        # This is fine, create new
        pass

    if not organization_on_stage_found:
        messages.add_message(request, messages.INFO,
                             'Could not find organization when trying to create a new position.')
        return HttpResponseRedirect(reverse('organization:organization_position_list', args=([organization_id])))

    if positive_value_exists(google_civic_election_id):
        google_civic_election_id_list = [google_civic_election_id]
    elif not show_all_elections:
        google_civic_election_id_list = retrieve_upcoming_election_id_list(limit_to_this_state_code=state_code)
    else:
        google_civic_election_id_list = []

    # Prepare a drop down of candidates competing in this election
    candidate_campaign_list = CandidateCampaignListManager()
    candidate_campaigns_for_this_election_list = []
    results = candidate_campaign_list.retrieve_all_candidates_for_upcoming_election(google_civic_election_id_list,
                                                                                    state_code, True)
    if results['candidate_list_found']:
        candidate_campaigns_for_this_election_list = results['candidate_list_objects']

    # Prepare a drop down of measures in this election
    contest_measure_list = ContestMeasureListManager()
    contest_measures_for_this_election_list = []
    results = contest_measure_list.retrieve_all_measures_for_upcoming_election(google_civic_election_id_list,
                                                                               state_code, True)
    if results['measure_list_found']:
        contest_measures_for_this_election_list = results['measure_list_objects']

    try:
        organization_position_query = PositionEntered.objects.order_by('stance')
        # As of Aug 2018 we are no longer using PERCENT_RATING
        organization_position_query = organization_position_query.exclude(stance__iexact='PERCENT_RATING')
        organization_position_query = organization_position_query.filter(organization_id=organization_id)
        if positive_value_exists(google_civic_election_id):
            organization_position_query = organization_position_query.filter(
                google_civic_election_id=google_civic_election_id)
        organization_position_list = organization_position_query.order_by(
            'google_civic_election_id', '-vote_smart_time_span')
        if len(organization_position_list):
            organization_position_list_found = True
    except Exception as e:
        organization_position_list = []

    if all_is_well:
        election_manager = ElectionManager()
        if positive_value_exists(show_all_elections):
            results = election_manager.retrieve_elections()
            election_list = results['election_list']
        else:
            results = election_manager.retrieve_upcoming_elections()
            election_list = results['election_list']
            # Make sure we always include the current election in the election_list, even if it is older
            if positive_value_exists(google_civic_election_id):
                this_election_found = False
                for one_election in election_list:
                    if convert_to_int(one_election.google_civic_election_id) == convert_to_int(google_civic_election_id):
                        this_election_found = True
                        break
                if not this_election_found:
                    results = election_manager.retrieve_election(google_civic_election_id)
                    if results['election_found']:
                        one_election = results['election']
                        election_list.append(one_election)

        template_values = {
            'candidate_campaigns_for_this_election_list':   candidate_campaigns_for_this_election_list,
            'candidate_campaign_id':                        candidate_campaign_id,
            'contest_measures_for_this_election_list':      contest_measures_for_this_election_list,
            'contest_measure_id':                           contest_measure_id,
            'messages_on_stage':                            messages_on_stage,
            'organization':                                 organization_on_stage,
            'organization_position_candidate_campaign_id':  0,
            'possible_stances_list':                        ORGANIZATION_STANCE_CHOICES,
            'show_all_elections':                           show_all_elections,
            'stance_selected':                              stance,
            'election_list':                                election_list,
            'google_civic_election_id':                     google_civic_election_id,
            'state_code':                                   state_code,
            'organization_position_list':                   organization_position_list,
            'organization_num_positions':                   len(organization_position_list),
            'voter_authority':                              authority_results,
            # Incoming values from error state
            'candidate_and_measure_not_found':              candidate_and_measure_not_found,
            'stance':                                       stance,
            'statement_text':                               statement_text,
            'more_info_url':                                more_info_url,
        }
    return render(request, 'organization/organization_position_edit.html', template_values)


@login_required
def organization_delete_existing_position_process_form_view(request, organization_id, position_we_vote_id):
    """

    :param request:
    :param organization_id:
    :param position_we_vote_id:
    :return:
    """
    # admin, analytics_admin, partner_organization, political_data_manager, political_data_viewer, verified_volunteer
    authority_required = {'admin', 'political_data_manager'}
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    organization_id = convert_to_int(organization_id)

    # Get the existing position
    organization_position_on_stage_found = False
    if positive_value_exists(position_we_vote_id):
        organization_position_on_stage = PositionEntered()
        organization_position_on_stage_found = False
        position_manager = PositionManager()
        results = position_manager.retrieve_position_from_we_vote_id(position_we_vote_id)
        if results['position_found']:
            organization_position_on_stage_found = True
            organization_position_on_stage = results['position']

    if not organization_position_on_stage_found:
        messages.add_message(request, messages.INFO,
                             "Could not find this organization's position when trying to delete.")
        return HttpResponseRedirect(reverse('organization:organization_position_list', args=([organization_id])))

    try:
        organization_position_on_stage.delete()
    except Exception as e:
        handle_record_not_deleted_exception(e, logger=logger)
        messages.add_message(request, messages.ERROR,
                             'Could not delete position.')
        return HttpResponseRedirect(reverse('organization:organization_position_list', args=([organization_id])))

    messages.add_message(request, messages.INFO,
                         'Position deleted.')
    return HttpResponseRedirect(reverse('organization:organization_position_list', args=([organization_id])))


@login_required
def organization_position_edit_view(request, organization_id=0, organization_we_vote_id="", position_we_vote_id=""):
    """
    In edit, you can only change your stance and comments, not who or what the position is about
    :param request:
    :param organization_id:
    :param position_we_vote_id:
    :return:
    """
    # admin, analytics_admin, partner_organization, political_data_manager, political_data_viewer, verified_volunteer
    authority_required = {'political_data_manager', 'verified_volunteer'}
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    google_civic_election_id = request.GET.get('google_civic_election_id', 0)
    show_all_elections = positive_value_exists(request.GET.get('show_all_elections', False))

    messages_on_stage = get_messages(request)
    organization_id = convert_to_int(organization_id)
    organization_on_stage_found = False
    try:
        if positive_value_exists(organization_id):
            organization_on_stage = Organization.objects.get(id=organization_id)
        else:
            organization_on_stage = Organization.objects.get(we_vote_id=organization_we_vote_id)
        organization_on_stage_found = True
    except Organization.MultipleObjectsReturned as e:
        handle_record_found_more_than_one_exception(e, logger=logger)
    except Organization.DoesNotExist:
        # This is fine, create new
        pass

    if not organization_on_stage_found:
        messages.add_message(request, messages.INFO,
                             'Could not find organization when trying to edit a position.')
        return HttpResponseRedirect(reverse('organization:organization_position_list', args=([organization_id])))

    # Get the existing position
    organization_position_on_stage = PositionEntered()
    organization_position_on_stage_found = False
    position_manager = PositionManager()
    results = position_manager.retrieve_position_from_we_vote_id(position_we_vote_id)
    if results['position_found']:
        organization_position_on_stage_found = True
        organization_position_on_stage = results['position']

    if not organization_position_on_stage_found:
        messages.add_message(request, messages.INFO,
                             'Could not find organization position when trying to edit.')
        return HttpResponseRedirect(reverse('organization:organization_position_list', args=([organization_id])))

    # Note: We have access to the candidate campaign through organization_position_on_stage.candidate_campaign

    election_manager = ElectionManager()
    if positive_value_exists(show_all_elections):
        results = election_manager.retrieve_elections()
        election_list = results['election_list']
    else:
        results = election_manager.retrieve_upcoming_elections()
        election_list = results['election_list']
        # Make sure we always include the current election in the election_list, even if it is older
        if positive_value_exists(google_civic_election_id):
            this_election_found = False
            for one_election in election_list:
                if convert_to_int(one_election.google_civic_election_id) == convert_to_int(google_civic_election_id):
                    this_election_found = True
                    break
            if not this_election_found:
                results = election_manager.retrieve_election(google_civic_election_id)
                if results['election_found']:
                    one_election = results['election']
                    election_list.append(one_election)

    if organization_position_on_stage_found:
        template_values = {
            'is_in_edit_mode':                              True,
            'messages_on_stage':                            messages_on_stage,
            'organization':                                 organization_on_stage,
            'organization_position':                        organization_position_on_stage,
            'possible_stances_list':                        ORGANIZATION_STANCE_CHOICES,
            'show_all_elections':                           show_all_elections,
            'stance_selected':                              organization_position_on_stage.stance,
            'election_list':                                election_list,
            'google_civic_election_id':                     google_civic_election_id,
        }

    return render(request, 'organization/organization_position_edit.html', template_values)


@login_required
def organization_position_edit_process_view(request):
    """

    :param request:
    :return:
    """
    # admin, analytics_admin, partner_organization, political_data_manager, political_data_viewer, verified_volunteer
    authority_required = {'political_data_manager', 'verified_volunteer'}
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    google_civic_election_id = convert_to_int(request.POST.get('google_civic_election_id', 0))
    organization_id = convert_to_int(request.POST.get('organization_id', 0))
    position_we_vote_id = request.POST.get('position_we_vote_id', '')
    candidate_campaign_id = convert_to_int(request.POST.get('candidate_campaign_id', 0))
    contest_measure_id = convert_to_int(request.POST.get('contest_measure_id', 0))
    stance = request.POST.get('stance', SUPPORT)  # Set a default if stance comes in empty
    statement_text = request.POST.get('statement_text', '')  # Set a default if stance comes in empty
    more_info_url = request.POST.get('more_info_url', '')
    show_all_elections = positive_value_exists(request.POST.get('show_all_elections', False))
    save_button = positive_value_exists(request.POST.get('save_button', False))

    go_back_to_add_new = False
    candidate_campaign_we_vote_id = ""
    google_civic_candidate_name = ""
    contest_measure_we_vote_id = ""
    google_civic_measure_title = ""
    candidate_campaign_on_stage_found = False
    contest_measure_on_stage_found = False
    organization_position_on_stage = PositionEntered()
    organization_on_stage = Organization()
    candidate_campaign_on_stage = CandidateCampaign()
    contest_measure_on_stage = ContestMeasure()
    state_code = ""
    position_manager = PositionManager()

    # Make sure this is a valid organization before we try to save a position
    organization_on_stage_found = False
    organization_we_vote_id = ""
    try:
        organization_query = Organization.objects.filter(id=organization_id)
        if organization_query.count():
            organization_on_stage = organization_query[0]
            organization_we_vote_id = organization_on_stage.we_vote_id
            organization_on_stage_found = True
    except Exception as e:
        # If we can't retrieve the organization, we cannot proceed
        handle_record_not_found_exception(e, logger=logger)

    if not organization_on_stage_found:
        messages.add_message(
            request, messages.ERROR,
            "Could not find the organization when trying to create or edit a new position.")
        return HttpResponseRedirect(reverse('organization:organization_list', args=()))

    # Now retrieve the CandidateCampaign or the ContestMeasure so we can save it with the Position
    # We need either candidate_campaign_id or contest_measure_id
    if candidate_campaign_id:
        try:
            candidate_campaign_on_stage = CandidateCampaign.objects.get(id=candidate_campaign_id)
            candidate_campaign_on_stage_found = True
            candidate_campaign_we_vote_id = candidate_campaign_on_stage.we_vote_id
            google_civic_candidate_name = candidate_campaign_on_stage.google_civic_candidate_name
            state_code = candidate_campaign_on_stage.state_code
        except CandidateCampaign.MultipleObjectsReturned as e:
            handle_record_found_more_than_one_exception(e, logger=logger)
        except CandidateCampaign.DoesNotExist as e:
            handle_record_not_found_exception(e, logger=logger)

        if candidate_campaign_on_stage_found:
            pass
        else:
            messages.add_message(
                request, messages.ERROR,
                "Could not find Candidate's campaign when trying to create or edit a new position.")
            if positive_value_exists(position_we_vote_id):
                url_variables = "?google_civic_election_id=" + str(google_civic_election_id)
                url_variables += "&state_code=" + str(state_code)
                if positive_value_exists(show_all_elections):
                    url_variables += "&show_all_elections=1"
                url_variables += "&stance=" + str(stance)
                url_variables += "&statement_text=" + str(statement_text)
                url_variables += "&more_info_url=" + str(more_info_url)
                url_variables += "&candidate_and_measure_not_found=1"

                return HttpResponseRedirect(
                    reverse('organization:organization_position_edit',
                            args=([organization_id], [position_we_vote_id])) + url_variables
                )
            else:
                url_variables = "?google_civic_election_id=" + str(google_civic_election_id)
                url_variables += "&state_code=" + str(state_code)
                if positive_value_exists(show_all_elections):
                    url_variables += "&show_all_elections=1"
                url_variables += "&stance=" + str(stance)
                url_variables += "&statement_text=" + str(statement_text)
                url_variables += "&more_info_url=" + str(more_info_url)
                url_variables += "&candidate_and_measure_not_found=1"

                return HttpResponseRedirect(
                    reverse('organization:organization_position_new', args=([organization_id])) + url_variables
                )
        contest_measure_id = 0
    elif contest_measure_id:
        try:
            contest_measure_on_stage = ContestMeasure.objects.get(id=contest_measure_id)
            contest_measure_on_stage_found = True
            contest_measure_we_vote_id = contest_measure_on_stage.we_vote_id
            google_civic_measure_title = contest_measure_on_stage.google_civic_measure_title
            state_code = contest_measure_on_stage.state_code
        except CandidateCampaign.MultipleObjectsReturned as e:
            handle_record_found_more_than_one_exception(e, logger=logger)
        except CandidateCampaign.DoesNotExist as e:
            handle_record_not_found_exception(e, logger=logger)

        if not contest_measure_on_stage_found:
            messages.add_message(
                request, messages.ERROR,
                "Could not find measure when trying to create or edit a new position.")
            if positive_value_exists(position_we_vote_id):
                url_variables = "?google_civic_election_id=" + str(google_civic_election_id)
                url_variables += "&state_code=" + str(state_code)
                if positive_value_exists(show_all_elections):
                    url_variables += "&show_all_elections=1"
                url_variables += "&stance=" + str(stance)
                url_variables += "&statement_text=" + str(statement_text)
                url_variables += "&more_info_url=" + str(more_info_url)
                url_variables += "&candidate_and_measure_not_found=1"

                return HttpResponseRedirect(
                    reverse('organization:organization_position_edit',
                            args=([organization_id], [position_we_vote_id])) + url_variables
                )
            else:
                url_variables = "?google_civic_election_id=" + str(google_civic_election_id)
                url_variables += "&state_code=" + str(state_code)
                if positive_value_exists(show_all_elections):
                    url_variables += "&show_all_elections=1"
                url_variables += "&stance=" + str(stance)
                url_variables += "&statement_text=" + str(statement_text)
                url_variables += "&more_info_url=" + str(more_info_url)
                url_variables += "&candidate_and_measure_not_found=1"

                return HttpResponseRedirect(
                    reverse('organization:organization_position_new', args=([organization_id])) + url_variables
                )
        candidate_campaign_id = 0
    else:
        messages.add_message(
            request, messages.ERROR,
            "Unable to find either Candidate or Measure.")
        url_variables = "?google_civic_election_id=" + str(google_civic_election_id)
        url_variables += "&state_code=" + str(state_code)
        if positive_value_exists(show_all_elections):
            url_variables += "&show_all_elections=1"
        url_variables += "&stance=" + str(stance)
        url_variables += "&statement_text=" + str(statement_text)
        url_variables += "&more_info_url=" + str(more_info_url)
        url_variables += "&candidate_and_measure_not_found=1"

        return HttpResponseRedirect(
            reverse('organization:organization_position_new', args=([organization_id])) +
            url_variables
        )

    organization_position_on_stage_found = False

    # Retrieve position from position_we_vote_id if it exists already
    if positive_value_exists(position_we_vote_id):
        results = position_manager.retrieve_position_from_we_vote_id(position_we_vote_id)
        if results['position_found']:
            organization_position_on_stage_found = True
            organization_position_on_stage = results['position']

    organization_position_found_from_new_form = False
    if not organization_position_on_stage_found:  # Position not found from position_we_vote_id
        # If a position_we_vote_id hasn't been passed in, then we are trying to create a new position.
        # Check to make sure a position for this org, candidate and election doesn't already exist
        if candidate_campaign_id:
            results = position_manager.retrieve_organization_candidate_campaign_position(
                organization_id, candidate_campaign_id, google_civic_election_id)
        elif contest_measure_id:
            results = position_manager.retrieve_organization_contest_measure_position(
                organization_id, contest_measure_id, google_civic_election_id)
        else:
            messages.add_message(
                request, messages.ERROR,
                "Missing both candidate_campaign_id and contest_measure_id.")
            return HttpResponseRedirect(
                reverse('organization:organization_position_list', args=([organization_id]))
            )

        if results['MultipleObjectsReturned']:
            messages.add_message(
                request, messages.ERROR,
                "We found more than one existing positions for this candidate. Please delete all but one position.")
            return HttpResponseRedirect(
                reverse('organization:organization_position_list', args=([organization_id]))
            )
        elif results['position_found']:
            organization_position_on_stage_found = True
            organization_position_on_stage = results['position']
            organization_position_found_from_new_form = True

    # Now save existing, or create new
    if positive_value_exists(save_button):
        success = False
        try:
            if organization_position_on_stage_found:
                # Update the position
                organization_position_on_stage.stance = stance
                organization_position_on_stage.google_civic_election_id = google_civic_election_id
                if not organization_position_found_from_new_form or positive_value_exists(more_info_url):
                    # Only update this if we came from update form, or there is a value in the incoming variable
                    organization_position_on_stage.more_info_url = more_info_url
                if not organization_position_found_from_new_form or positive_value_exists(statement_text):
                    # Only update this if we came from update form, or there is a value in the incoming variable
                    organization_position_on_stage.statement_text = statement_text
                if not positive_value_exists(organization_position_on_stage.organization_we_vote_id):
                    organization_position_on_stage.organization_we_vote_id = organization_on_stage.we_vote_id
                organization_position_on_stage.candidate_campaign_id = candidate_campaign_id
                organization_position_on_stage.candidate_campaign_we_vote_id = candidate_campaign_we_vote_id
                organization_position_on_stage.google_civic_candidate_name = google_civic_candidate_name
                organization_position_on_stage.contest_measure_id = contest_measure_id
                organization_position_on_stage.contest_measure_we_vote_id = contest_measure_we_vote_id
                organization_position_on_stage.google_civic_measure_title = google_civic_measure_title
                organization_position_on_stage.state_code = state_code
                organization_position_on_stage.save()

                results = position_manager.refresh_cached_position_info(organization_position_on_stage)

                success = True

                if positive_value_exists(candidate_campaign_we_vote_id):
                    messages.add_message(
                        request, messages.INFO,
                        "Position on {candidate_name} updated.".format(
                            candidate_name=candidate_campaign_on_stage.display_candidate_name()))
                elif positive_value_exists(contest_measure_we_vote_id):
                    messages.add_message(
                        request, messages.INFO,
                        "Position on {measure_title} updated.".format(
                            measure_title=contest_measure_on_stage.measure_title))
            else:
                # Create new
                # Note that since we are processing a volunteer/admin entry tool, we can always save the PositionEntered
                # table, and don't need to worry about PositionForFriends
                organization_position_on_stage = PositionEntered(
                    organization_id=organization_id,
                    organization_we_vote_id=organization_we_vote_id,
                    candidate_campaign_id=candidate_campaign_id,
                    candidate_campaign_we_vote_id=candidate_campaign_we_vote_id,
                    google_civic_candidate_name=google_civic_candidate_name,
                    contest_measure_id=contest_measure_id,
                    contest_measure_we_vote_id=contest_measure_we_vote_id,
                    google_civic_measure_title=google_civic_measure_title,
                    google_civic_election_id=google_civic_election_id,
                    stance=stance,
                    statement_text=statement_text,
                    more_info_url=more_info_url,
                    state_code=state_code,
                )
                organization_position_on_stage.save()

                results = position_manager.refresh_cached_position_info(organization_position_on_stage)
                success = True

                if positive_value_exists(candidate_campaign_we_vote_id):
                    messages.add_message(
                        request, messages.INFO,
                        "New position on {candidate_name} saved.".format(
                            candidate_name=candidate_campaign_on_stage.display_candidate_name()))
                elif positive_value_exists(contest_measure_we_vote_id):
                    messages.add_message(
                        request, messages.INFO,
                        "New position on {measure_title} saved.".format(
                            measure_title=contest_measure_on_stage.measure_title))
                go_back_to_add_new = True
        except Exception as e:
            pass
        # If the position was saved, then update the voter_guide entry
        if success:
            voter_guide_manager = VoterGuideManager()
            voter_guide_we_vote_id = ''
            results = voter_guide_manager.update_or_create_organization_voter_guide_by_election_id(
                voter_guide_we_vote_id, organization_on_stage.we_vote_id, google_civic_election_id, state_code)
            # if results['success']:
    else:
        go_back_to_add_new = True

    if go_back_to_add_new:
        url_variables = "?google_civic_election_id=" + str(google_civic_election_id)
        url_variables += "&state_code=" + str(state_code)
        if positive_value_exists(candidate_campaign_id):
            url_variables += "&candidate_campaign_id=" + str(candidate_campaign_id)
        if positive_value_exists(show_all_elections):
            url_variables += "&show_all_elections=1"
        url_variables += "&contest_measure_id=" + str(contest_measure_id)
        url_variables += "&stance=" + str(stance)
        url_variables += "&statement_text=" + str(statement_text)
        url_variables += "&more_info_url=" + str(more_info_url)

        return HttpResponseRedirect(
            reverse('organization:organization_position_new', args=(organization_on_stage.id,)) +
            url_variables)
    else:
        return HttpResponseRedirect(
            reverse('organization:organization_position_list', args=(organization_on_stage.id,)))


def render_organization_merge_form(
        request, organization_option1_for_template, organization_option2_for_template,
        organization_merge_conflict_values, remove_duplicate_process=True):
    organization_list_manager = OrganizationListManager()
    position_list_manager = PositionListManager()

    # Get positions counts for both organizations
    organization_option1_for_template.public_positions_count = \
        position_list_manager.fetch_public_positions_count_for_organization(
            organization_option1_for_template.id, organization_option1_for_template.we_vote_id)
    organization_option1_for_template.friends_positions_count = \
        position_list_manager.fetch_friends_only_positions_count_for_organization(
            organization_option1_for_template.id, organization_option1_for_template.we_vote_id)

    organization_option2_for_template.public_positions_count = \
        position_list_manager.fetch_public_positions_count_for_organization(
            organization_option2_for_template.id, organization_option2_for_template.we_vote_id)
    organization_option2_for_template.friends_positions_count = \
        position_list_manager.fetch_friends_only_positions_count_for_organization(
            organization_option2_for_template.id, organization_option2_for_template.we_vote_id)

    messages_on_stage = get_messages(request)
    template_values = {
        'messages_on_stage': messages_on_stage,
        'organization_option1': organization_option1_for_template,
        'organization_option2': organization_option2_for_template,
        'conflict_values': organization_merge_conflict_values,
        'remove_duplicate_process': remove_duplicate_process,
    }
    return render(request, 'organization/organization_merge.html', template_values)


@login_required
def reserved_domain_edit_view(request):
    """
    In edit, you can only change your stance and comments, not who or what the position is about
    :param request:
    :return:
    """
    # admin, analytics_admin, partner_organization, political_data_manager, political_data_viewer, verified_volunteer
    authority_required = {'political_data_manager'}
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    google_civic_election_id = request.GET.get('google_civic_election_id', 0)
    google_civic_election_id = convert_to_int(google_civic_election_id)
    reserved_domain_id = request.GET.get('reserved_domain_id', 0)
    reserved_domain_id = convert_to_int(reserved_domain_id)
    state_code = request.GET.get('state_code', '')

    messages_on_stage = get_messages(request)
    google_civic_election_id = convert_to_int(google_civic_election_id)
    full_domain_string = ''
    subdomain_string = ''
    reserved_domain_found = False
    try:
        if positive_value_exists(reserved_domain_id):
            reserved_domain = OrganizationReservedDomain.objects.get(id=reserved_domain_id)
            full_domain_string = reserved_domain.full_domain_string
            subdomain_string = reserved_domain.subdomain_string
            reserved_domain_found = True
    except OrganizationReservedDomain.MultipleObjectsReturned as e:
        messages.add_message(request, messages.INFO,
                             'Could not find reserved domain when trying to edit.')
    except OrganizationReservedDomain.DoesNotExist:
        # This is fine, create new
        pass

    template_values = {
        'google_civic_election_id': google_civic_election_id,
        'messages_on_stage':        messages_on_stage,
        'full_domain_string':       full_domain_string,
        'reserved_domain_id':       reserved_domain_id,
        'reserved_domain_found':    reserved_domain_found,
        'state_code':               state_code,
        'subdomain_string':         subdomain_string,
    }

    return render(request, 'organization/reserved_domain_edit.html', template_values)


@login_required
def reserved_domain_edit_process_view(request):
    """
    Process the new or edit reserved domain form
    :param request:
    :return:
    """
    # admin, analytics_admin, partner_organization, political_data_manager, political_data_viewer, verified_volunteer
    authority_required = {'political_data_manager'}
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    reserved_domain = None

    full_domain_string = request.POST.get('full_domain_string', '')
    reserved_domain_id = convert_to_int(request.POST.get('reserved_domain_id', 0))
    subdomain_string = request.POST.get('subdomain_string', '')

    google_civic_election_id = request.POST.get('google_civic_election_id', 0)
    state_code = request.POST.get('state_code', False)

    if not positive_value_exists(full_domain_string) and not positive_value_exists(subdomain_string):
        messages.add_message(request, messages.INFO, 'Please enter either a full domain, or a sub domain.')
        messages_on_stage = get_messages(request)
        template_values = {
            'full_domain_string':       full_domain_string,
            'google_civic_election_id': google_civic_election_id,
            'messages_on_stage':        messages_on_stage,
            'reserved_domain_id':       reserved_domain_id,
            'state_code':               state_code,
            'subdomain_string':         subdomain_string,
        }

        return render(request, 'organization/reserved_domain_edit.html', template_values)

    # Check to see if this organization is already being used anywhere
    reserved_domain_found = False
    new_organization_created = False
    status = ""
    if positive_value_exists(reserved_domain_id):
        try:
            reserved_domain = OrganizationReservedDomain.objects.get(id=reserved_domain_id)
            reserved_domain_found = True
        except Exception as e:
            messages.add_message(request, messages.ERROR, 'Could not find existing reserved domain.'
                                                          ' {error} [type: {error_type}]'
                                                          ''.format(error=e, error_type=type(e)))

    organization_domain_list = []
    reserved_domain_list = []
    if positive_value_exists(full_domain_string) or positive_value_exists(subdomain_string):
        # Double-check that we don't have a reserved entry already in the Organization table
        try:
            organization_list_query = Organization.objects.using('readonly').all()
            if positive_value_exists(full_domain_string):
                organization_list_query = organization_list_query.filter(chosen_domain_string__iexact=full_domain_string)
            else:
                organization_list_query = organization_list_query.\
                    filter(chosen_subdomain_string__iexact=subdomain_string)
            organization_domain_list = list(organization_list_query)
        except Exception as e:
            messages.add_message(request, messages.ERROR, 'Could not find existing organization domain.'
                                                          ' {error} [type: {error_type}]'
                                                          ''.format(error=e, error_type=type(e)))

        # Double-check that we don't have a reserved entry already in the OrganizationReservedDomain table
        try:
            reserved_domain_list_query = OrganizationReservedDomain.objects.using('readonly').all()
            if positive_value_exists(reserved_domain_id):
                # Don't include this reserved_domain in the query
                reserved_domain_list_query = reserved_domain_list_query.exclude(id=reserved_domain_id)
            if positive_value_exists(full_domain_string):
                reserved_domain_list_query = reserved_domain_list_query.\
                    filter(full_domain_string__iexact=full_domain_string)
            else:
                reserved_domain_list_query = reserved_domain_list_query.filter(subdomain_string__iexact=subdomain_string)
            reserved_domain_list = list(reserved_domain_list_query)
        except Exception as e:
            messages.add_message(request, messages.ERROR, 'Could not find existing reserved domain.'
                                                          ' {error} [type: {error_type}]'
                                                          ''.format(error=e, error_type=type(e)))

    if len(reserved_domain_list) or len(organization_domain_list):
        # Cannot save this entry
        messages.add_message(request, messages.INFO, 'Reserved domain already taken.')
        messages_on_stage = get_messages(request)
        template_values = {
            'full_domain_string':       full_domain_string,
            'google_civic_election_id': google_civic_election_id,
            'messages_on_stage':        messages_on_stage,
            'organization_domain_list': organization_domain_list,
            'reserved_domain_list':     reserved_domain_list,
            'reserved_domain_id':       reserved_domain_id,
            'state_code':               state_code,
            'subdomain_string':         subdomain_string,
        }

        return render(request, 'organization/reserved_domain_edit.html', template_values)

    if reserved_domain_found:
        # Update
        try:
            string_updated = ''
            if positive_value_exists(full_domain_string):
                reserved_domain.full_domain_string = full_domain_string.strip()
                string_updated = full_domain_string.strip()
            else:
                reserved_domain.full_domain_string = None
            if positive_value_exists(subdomain_string):
                reserved_domain.subdomain_string = subdomain_string.strip()
                string_updated = subdomain_string.strip()
            else:
                reserved_domain.subdomain_string = None
            reserved_domain.save()
            reserved_domain_id = reserved_domain.id

            messages.add_message(request, messages.INFO,
                                 'Reserved domain \'{string_updated}\' updated.'
                                 ''.format(string_updated=string_updated))
        except Exception as e:
            messages.add_message(request, messages.ERROR, 'Could not update reserved domain.'
                                                          ' {error} [type: {error_type}]'.format(error=e,
                                                                                                 error_type=type(e)))
    else:
        # Create new
        try:
            if positive_value_exists(full_domain_string):
                reserved_domain = OrganizationReservedDomain.objects.create(
                    full_domain_string=full_domain_string,
                )
                messages.add_message(request, messages.INFO, 'New reserved full domain saved.')
            elif positive_value_exists(subdomain_string):
                reserved_domain = OrganizationReservedDomain.objects.create(
                    subdomain_string=subdomain_string,
                )
                messages.add_message(request, messages.INFO, 'New reserved sub domain saved.')
            else:
                messages.add_message(request, messages.ERROR, 'Reserved full or sub domain not saved.')

        except Exception as e:
            messages.add_message(request, messages.ERROR, 'Could not save new reserved domain.'
                                                          ' {error} [type: {error_type}]'.format(error=e,
                                                                                                 error_type=type(e)))
    return HttpResponseRedirect(reverse('organization:reserved_domain_list', args=()) +
                                "?google_civic_election_id=" + str(google_civic_election_id) + "&state_code=" +
                                str(state_code))


@login_required
def reserved_domain_list_view(request):
    # admin, analytics_admin, partner_organization, political_data_manager, political_data_viewer, verified_volunteer
    authority_required = {'political_data_manager'}
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    domain_search = request.GET.get('domain_search', '')
    google_civic_election_id = request.GET.get('google_civic_election_id', '')
    show_all = request.GET.get('show_all', False)
    show_full_domains = request.GET.get('show_full_domains', False)
    show_more = request.GET.get('show_more', False)
    show_subdomains = request.GET.get('show_subdomains', False)
    state_code = request.GET.get('state_code', '')

    messages_on_stage = get_messages(request)

    # ##########################################
    # Pull from OrganizationReservedDomain table
    reserved_domain_list_query = OrganizationReservedDomain.objects.using('readonly').all()
    if positive_value_exists(show_full_domains) and not positive_value_exists(show_subdomains):
        reserved_domain_list_query = reserved_domain_list_query.exclude(full_domain_string__isnull=True). \
            exclude(full_domain_string__exact='')
        reserved_domain_list_query = reserved_domain_list_query.order_by('full_domain_string')
    elif positive_value_exists(show_subdomains) and not positive_value_exists(show_full_domains):
        reserved_domain_list_query = reserved_domain_list_query.exclude(subdomain_string__isnull=True). \
            exclude(subdomain_string__exact='')
        reserved_domain_list_query = reserved_domain_list_query.order_by('subdomain_string')
    else:
        reserved_domain_list_query = reserved_domain_list_query.order_by('subdomain_string').\
            order_by('full_domain_string')

    if positive_value_exists(domain_search):
        search_words = domain_search.split()
        for one_word in search_words:
            filters = []
            new_filter = Q(full_domain_string__icontains=one_word)
            filters.append(new_filter)

            new_filter = Q(subdomain_string__icontains=one_word)
            filters.append(new_filter)

            # Add the first query
            if len(filters):
                final_filters = filters.pop()

                # ...and "OR" the remaining items in the list
                for item in filters:
                    final_filters |= item

                reserved_domain_list_query = reserved_domain_list_query.filter(final_filters)

    reserved_domain_count = reserved_domain_list_query.count()

    # Limit to only showing 200 on screen
    if positive_value_exists(show_more):
        reserved_domain_list = reserved_domain_list_query[:1000]
    elif positive_value_exists(show_all):
        reserved_domain_list = reserved_domain_list_query
    else:
        reserved_domain_list = reserved_domain_list_query[:200]

    # ##########################################
    # Pull from Organization table
    organization_domain_list_query = Organization.objects.using('readonly').all()
    # organization_domain_list_query = organization_domain_list_query. \
    #     exclude(chosen_domain_string__isnull=True). \
    #     exclude(chosen_domain_string__exact=''). \
    #     exclude(chosen_subdomain_string__isnull=True). \
    #     exclude(chosen_subdomain_string__exact='')
    if positive_value_exists(show_full_domains) and not positive_value_exists(show_subdomains):
        organization_domain_list_query = organization_domain_list_query.filter(chosen_domain_string__isnull=False)
        organization_domain_list_query = organization_domain_list_query.order_by('chosen_domain_string')
    elif positive_value_exists(show_subdomains) and not positive_value_exists(show_full_domains):
        organization_domain_list_query = organization_domain_list_query.filter(chosen_subdomain_string__isnull=False)
        organization_domain_list_query = organization_domain_list_query.order_by('chosen_subdomain_string')
    else:
        organization_domain_list_query = organization_domain_list_query.filter(
            Q(chosen_domain_string__isnull=False) |
            Q(chosen_subdomain_string__isnull=False)
        )
        organization_domain_list_query = organization_domain_list_query.order_by('chosen_subdomain_string').\
            order_by('chosen_domain_string')

    if positive_value_exists(domain_search):
        search_words = domain_search.split()
        for one_word in search_words:
            filters = []
            new_filter = Q(chosen_domain_string__icontains=one_word)
            filters.append(new_filter)

            new_filter = Q(chosen_subdomain_string__icontains=one_word)
            filters.append(new_filter)

            # Add the first query
            if len(filters):
                final_filters = filters.pop()

                # ...and "OR" the remaining items in the list
                for item in filters:
                    final_filters |= item

                organization_domain_list_query = organization_domain_list_query.filter(final_filters)

    organization_domain_count = organization_domain_list_query.count()

    # Limit to only showing 200 on screen
    if positive_value_exists(show_more):
        organization_domain_list = organization_domain_list_query[:1000]
    elif positive_value_exists(show_all):
        organization_domain_list = organization_domain_list_query
    else:
        organization_domain_list = organization_domain_list_query[:200]

    if positive_value_exists(organization_domain_count) or positive_value_exists(reserved_domain_count):
        messages.add_message(request, messages.INFO,
                             '{reserved_domain_count:,} reserved domains found. '
                             '{organization_domain_count:,} organization domains found. '
                             ''.format(organization_domain_count=organization_domain_count,
                                       reserved_domain_count=reserved_domain_count))

    template_values = {
        'domain_search':            domain_search,
        'google_civic_election_id': google_civic_election_id,
        'messages_on_stage':        messages_on_stage,
        'organization_domain_list': organization_domain_list,
        'reserved_domain_list':     reserved_domain_list,
        # 'show_all':                 show_all,
        # 'show_more':                show_more,
        'show_full_domains':        show_full_domains,
        'show_subdomains':          show_subdomains,
        # 'sort_by':                  sort_by,
        'state_code':               state_code,
    }
    return render(request, 'organization/reserved_domain_list.html', template_values)
