##############################################################################
#
# Copyright (c) 2014, 2degrees Limited.
# All Rights Reserved.
#
# This file is part of hubspot-contacts
# <https://github.com/2degrees/hubspot-contacts>, which is subject to the
# provisions of the BSD at
# <http://dev.2degreesnetwork.com/p/2degrees-license.html>. A copy of the
# license should accompany this distribution. THIS SOFTWARE IS PROVIDED "AS IS"
# AND ANY AND ALL EXPRESS OR IMPLIED WARRANTIES ARE DISCLAIMED, INCLUDING, BUT
# NOT LIMITED TO, THE IMPLIED WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST
# INFRINGEMENT, AND FITNESS FOR A PARTICULAR PURPOSE.
#
##############################################################################

from abc import abstractmethod
from abc import abstractproperty
from functools import partial

from nose.tools import assert_dict_contains_subset
from nose.tools import assert_in
from nose.tools import eq_

from hubspot.contacts import Contact
from hubspot.contacts import _HUBSPOT_BATCH_SAVING_SIZE_LIMIT
from hubspot.contacts import get_all_contacts
from hubspot.contacts import get_all_contacts_by_last_update
from hubspot.contacts import save_contacts
from hubspot.contacts.request_data_formatters.contacts import \
    format_contacts_data_for_saving
from hubspot.test_utils import MockPortalConnection
from hubspot.test_utils import RemoteMethod

from tests.utils import BaseMethodTestCase
from tests.utils.contact import make_contact
from tests.utils.contact import make_contacts
from tests.utils.response_data_formatters.contacts_retrieval import \
    format_data_from_all_contacts_retrieval
from tests.utils.response_data_formatters.contacts_retrieval import \
    format_data_from_all_contacts_by_last_update_retrieval
from tests.utils.response_data_formatters.contacts_retrieval import \
    STUB_TIMESTAMP


_HUBSPOT_DEFAULT_PAGE_SIZE = 100


class _BaseGettingAllContactsTestCase(BaseMethodTestCase):

    _RETRIEVER = abstractproperty()

    _RETRIEVED_DATA_FORMATTER = abstractproperty()

    def test_no_contacts(self):
        connection = self._make_connection([])

        self._assert_retrieved_contacts_match([], connection)

        self._assert_expected_remote_method_used(connection)

        eq_(1, len(connection.remote_method_invocations))

    def test_not_exceeding_pagination_size(self):
        contacts_count = _HUBSPOT_DEFAULT_PAGE_SIZE - 1
        expected_contacts = make_contacts(contacts_count)
        connection = self._make_connection(expected_contacts)

        self._assert_retrieved_contacts_match(expected_contacts, connection)

        self._assert_expected_remote_method_used(connection)

        eq_(1, len(connection.remote_method_invocations))

    @abstractmethod
    def test_exceeding_pagination_size(self):
        pass

    def test_getting_existing_properties(self):
        expected_contacts = [
            make_contact(1, properties={'p1': 'foo'}),
            make_contact(2, properties={'p1': 'baz', 'p2': 'bar'}),
            ]
        connection = self._make_connection(expected_contacts)

        expected_contacts_with_expected_properties = []
        for original_contact in expected_contacts:
            expected_contact_with_expected_properties = Contact(
                original_contact.vid,
                original_contact.email_address,
                {'p1': original_contact.properties['p1']},
                [],
                )
            expected_contacts_with_expected_properties.append(
                expected_contact_with_expected_properties,
                )

        properties = ('p1',)
        self._assert_retrieved_contacts_match(
            expected_contacts_with_expected_properties,
            connection,
            properties=properties,
            )

        self._assert_expected_remote_method_used(connection)

        eq_(1, len(connection.remote_method_invocations))
        remote_method_invocation = connection.remote_method_invocations[0]
        eq_(2, len(remote_method_invocation.query_string_args))
        assert_in('property', remote_method_invocation.query_string_args)
        eq_(properties, remote_method_invocation.query_string_args['property'])

    def test_getting_non_existing_properties(self):
        """Requesting non-existing properties fails silently in HubSpot"""
        expected_contacts = make_contacts(_HUBSPOT_DEFAULT_PAGE_SIZE)
        connection = self._make_connection(expected_contacts)

        self._assert_retrieved_contacts_match(expected_contacts, connection)

        self._assert_expected_remote_method_used(connection)

        eq_(1, len(connection.remote_method_invocations))

    def test_contacts_with_sub_contacts(self):
        expected_sub_contacts = [2, 3]
        expected_contacts = make_contact(1, sub_contacts=expected_sub_contacts)
        connection = self._make_connection([expected_contacts])

        retrieved_contacts = self._RETRIEVER(connection)
        eq_(expected_sub_contacts, list(retrieved_contacts)[0].sub_contacts)

    def test_contacts_without_sub_contacts(self):
        expected_sub_contacts = []
        expected_contacts = make_contact(1, sub_contacts=expected_sub_contacts)
        connection = self._make_connection([expected_contacts])

        retrieved_contacts = self._RETRIEVER(connection)
        eq_(expected_sub_contacts, list(retrieved_contacts)[0].sub_contacts)

    def _assert_retrieved_contacts_match(
        self,
        expected_contacts,
        connection,
        *args,
        **kwargs
        ):
        retrieved_contacts = self._RETRIEVER(connection, *args, **kwargs)
        eq_(list(expected_contacts), list(retrieved_contacts))

    def _make_connection(self, contacts):
        response_data_maker = partial(self._replicate_response_data, contacts)
        response_data_maker_by_remote_method = \
            {self._REMOTE_METHOD: response_data_maker}
        return MockPortalConnection(response_data_maker_by_remote_method)

    def _replicate_response_data(
        self,
        contacts,
        query_string_args,
        body_deserialization,
        ):
        last_contact_vid = query_string_args.get('vidOffset')
        properties = query_string_args.get('property', [])

        contacts_in_page = _get_contacts_in_page(
            contacts,
            last_contact_vid,
            _HUBSPOT_DEFAULT_PAGE_SIZE,
            )
        contacts_in_page = \
            _get_contacts_with_properties_filtered(contacts_in_page, properties)
        contacts_in_page_data = self._RETRIEVED_DATA_FORMATTER(
            contacts_in_page,
            contacts,
            _HUBSPOT_DEFAULT_PAGE_SIZE,
            )
        return contacts_in_page_data


class TestGettingAllContacts(_BaseGettingAllContactsTestCase):

    _REMOTE_METHOD = RemoteMethod('/lists/all/contacts/all', 'GET')

    _RETRIEVER = staticmethod(get_all_contacts)

    _RETRIEVED_DATA_FORMATTER = \
        staticmethod(format_data_from_all_contacts_retrieval)

    def test_exceeding_pagination_size(self):
        contacts_count = _HUBSPOT_DEFAULT_PAGE_SIZE + 1
        expected_contacts = make_contacts(contacts_count)
        connection = self._make_connection(expected_contacts)

        self._assert_retrieved_contacts_match(expected_contacts, connection)

        eq_(2, len(connection.remote_method_invocations))

        remote_method_invocation2 = connection.remote_method_invocations[1]
        eq_(2, len(remote_method_invocation2.query_string_args))

        assert_in('vidOffset', remote_method_invocation2.query_string_args)
        page1_last_contact = expected_contacts[_HUBSPOT_DEFAULT_PAGE_SIZE - 1]
        expect_vid_offset = page1_last_contact.vid
        eq_(
            expect_vid_offset,
            remote_method_invocation2.query_string_args['vidOffset'],
            )


def _get_contacts_in_page(contacts, last_contact_vid, page_size):
    start_index = 0
    if last_contact_vid:
        for contact_index, contact in enumerate(contacts):
            if contact.vid == last_contact_vid:
                start_index = contact_index + 1
                break
    end_index = start_index + page_size
    contacts_in_page = contacts[start_index:end_index]
    return contacts_in_page


def _get_contacts_with_properties_filtered(contacts, properties):
    if not properties:
        return contacts

    contacts_with_properties_filtered = []
    for contact in contacts:
        contact_with_properties_filtered = contact.copy()
        contact_with_properties_filtered.properties = \
            {k: v for k, v in contact.properties.items() if k in properties}

        contacts_with_properties_filtered. \
            append(contact_with_properties_filtered)

    return contacts_with_properties_filtered


class TestGettingAllContactsByLastUpdate(_BaseGettingAllContactsTestCase):

    _REMOTE_METHOD = \
        RemoteMethod('/lists/recently_updated/contacts/recent', 'GET')

    _RETRIEVER = staticmethod(get_all_contacts_by_last_update)

    _RETRIEVED_DATA_FORMATTER = \
        staticmethod(format_data_from_all_contacts_by_last_update_retrieval)

    def test_exceeding_pagination_size(self):
        contacts_count = _HUBSPOT_DEFAULT_PAGE_SIZE + 1
        expected_contacts = make_contacts(contacts_count)
        connection = self._make_connection(expected_contacts)

        self._assert_retrieved_contacts_match(expected_contacts, connection)

        self._assert_expected_remote_method_used(connection)

        eq_(2, len(connection.remote_method_invocations))

        remote_method_invocation2 = connection.remote_method_invocations[1]
        eq_(3, len(remote_method_invocation2.query_string_args))

        page1_last_contact = expected_contacts[_HUBSPOT_DEFAULT_PAGE_SIZE - 1]
        expected_query_string_args = {
            'vidOffset': page1_last_contact.vid,
            'timeOffset': STUB_TIMESTAMP,
            }
        assert_dict_contains_subset(
            expected_query_string_args,
            remote_method_invocation2.query_string_args,
            )


class TestSavingContacts(BaseMethodTestCase):

    _REMOTE_METHOD = RemoteMethod('/contact/batch/', 'POST')

    def setup(self):
        self.connection = MockPortalConnection()

    def test_no_contacts(self):
        contacts_generator = iter([])
        save_contacts(contacts_generator, self.connection)

        eq_(0, len(self.connection.remote_method_invocations))

    def test_without_exceeding_batch_size_limit(self):
        contacts = make_contacts(_HUBSPOT_BATCH_SAVING_SIZE_LIMIT)

        contacts_generator = iter(contacts)
        save_contacts(contacts_generator, self.connection)

        self._assert_expected_remote_method_used(self.connection)

        eq_(1, len(self.connection.remote_method_invocations))

        remote_method_invocation = self.connection.remote_method_invocations[0]
        self._assert_contacts_sent_in_request(
            contacts,
            remote_method_invocation,
            )

    def test_exceeding_batch_size_limit(self):
        contacts = make_contacts(_HUBSPOT_BATCH_SAVING_SIZE_LIMIT + 1)

        contacts_generator = iter(contacts)
        save_contacts(contacts_generator, self.connection)

        self._assert_expected_remote_method_used(self.connection)

        eq_(2, len(self.connection.remote_method_invocations))

        contacts1 = contacts[:_HUBSPOT_BATCH_SAVING_SIZE_LIMIT]
        remote_method_invocation1 = self.connection.remote_method_invocations[0]
        self._assert_contacts_sent_in_request(
            contacts1,
            remote_method_invocation1,
            )

        contacts2 = contacts[_HUBSPOT_BATCH_SAVING_SIZE_LIMIT:]
        remote_method_invocation2 = self.connection.remote_method_invocations[1]
        self._assert_contacts_sent_in_request(
            contacts2,
            remote_method_invocation2,
            )

    @staticmethod
    def _assert_contacts_sent_in_request(contacts, remote_method_invocation):
        contacts_data = format_contacts_data_for_saving(contacts)
        eq_(contacts_data, remote_method_invocation.body_deserialization)
