from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals
import csbc
import os
import re
import requests
import argparse
import getpass
import six
from Bio import Entrez
from bs4 import BeautifulSoup
import pandas
import datetime
import synapseutils
import synapseclient
from synapseclient import Entity, Project, Column, Team, Wiki


def synapseLogin():
    """
    First tries to login to synapse by finding the local auth key cached on user's computing platform, if not found,
    prompts the user to provide their synapse user name and password, then caches the auth key on their computing
    platform.

    :return:
    """
    try:
        syn = synapseclient.login()
    except Exception as e:
        print('Please provide your synapse username/email and password (You will only be prompted once)')
        username = input("Username: ")
        password = getpass.getpass(("Password for " + username + ": ").encode('utf-8'))
        syn = synapseclient.login(email=username, password=password, rememberMe=True)

    return syn


def createProject(syn, project_name, teamId=None, adminId=None):
    """
    Given a project name, creates a synapse project and sets permissions for All registered Synapse users and Anyone
    on the web to read/view, then given an admin and/or project team id it sets permissions for the team.

    :param syn:
    :param project_name: A title string for the synapse project
    :param teamId: A synapse team id (with-out 'syn')
    :param adminId: A synapse team id that would hold admin permissions to consortium
    :return: project synapse entity with permission settings
    """
    project = Project(project_name)
    project = syn.store(project)

    syn.setPermissions(entity=project, principalId='273948', accessType=['READ'])
    syn.setPermissions(entity=project, principalId='273949', accessType=['READ'])

    if teamId:
        syn.setPermissions(entity=project, principalId=teamId,
                           accessType=['CREATE', 'UPDATE', 'DELETE', 'DOWNLOAD', 'READ'])

    if adminId:
        syn.setPermissions(entity=project, principalId=adminId,
                           accessType=['CHANGE_SETTINGS', 'CHANGE_PERMISSIONS', 'MODERATE', 'READ', 'DOWNLOAD',
                                       'CREATE', 'DELETE', 'UPDATE'])

    return project


def updateProjectViewScope(syn, consortium_viewId, projectId):
    """
    Downloads current state of the consortium project view, adds new project synapse Id's to the scope, then stores
    the updated consortium project view.

    :param consortium_viewId: Consortium project view id on synapse
    :param projectId: Synapse project Id to be added to consortium project view scope
    :return: the updated stored consortium project view entity
    """
    project_view = syn.get(consortium_viewId)
    project_view.add_scope(projectId)
    project_view = syn.store(project_view)

    return project_view


def buildProject(syn, projectName, teamId, adminId, templateId, projectView):
    """

    :param syn:
    :param projectName:
    :param teamId:
    :param adminId:
    :param templateId:
    :param projectView:
    :return:
    """

    pc = createProject(syn, project_name=projectName, teamId=teamId, adminId=adminId)
    print("project %s location on synapse is %s" % (projectName, pc.id))

    copied_syn_dict = synapseutils.copy(syn, entity=templateId, destinationId=pc.id)

    pv = updateProjectViewScope(syn, projectView, pc.id)
    print("Updated csbc project view scope - needs updated annotations\n")


def template(args, syn):
    """

    :param args:
    :param syn:
    :return:
    """
    consortium = args.consortiumId
    project_name = args.projectName
    csbc_admin_teamId = '3346139'
    csbc_project_viewId = 'syn10142562'

    if args.teamId:
        teamId = args.teamId
    else:
        teamId = None

    if consortium not in ['U54','U01']:

        print("Please provide an existing consortium Id")

    else:

        if consortium in ['U54']:
            templateId = 'syn11801564'
            buildProject(syn, projectName=project_name, teamId=teamId, adminId=csbc_admin_teamId, templateId=templateId,
                         projectView=csbc_project_viewId)

        if consortium in ['U01']:
            templateId = 'syn11801693'
            buildProject(syn, projectName=project_name, teamId=teamId, adminId=csbc_admin_teamId, templateId=templateId,
                         projectView=csbc_project_viewId)


def csbcGrantList(syn, tableSynId):
    """

    :param syn:
    :param tableSynId:
    :return:
    """
    csbc = syn.tableQuery("select * from %s" % tableSynId)
    csbc = csbc.asDataFrame()
    csbc = list(csbc.grantNumber.dropna())
    return csbc


def getGrantQuery(csbc):
    """

    :param csbc:
    :return:
    """
    grantQuery = ' or '.join(csbc)
    return grantQuery


def getPubMedIds(query):
    """

    :param query:
    :return:
    """
    Entrez.email = 'nasim.sanati@sagebase.org'
    handle = Entrez.esearch(db='pubmed',
                            sort='relevance',
                            retmax='1000000',
                            retmode='xml',
                            term=query)
    results = Entrez.read(handle)
    PMIDs = results.get('IdList')
    return PMIDs


def getCenterIdsView(syn, viewSynId):
    """

    :param syn:
    :param viewSynId:
    :return:
    """
    csbcView = syn.tableQuery("select * from %s" % viewSynId)
    csbcView = csbcView.asDataFrame()
    csbcView = csbcView[~csbcView['grantNumber'].isnull()]
    return csbcView


def getPublishedGEO(pId):
    website = 'https://www.ncbi.nlm.nih.gov/gds?LinkName=pubmed_gds&from_uid=' + pId
    session = requests.Session()
    soup = BeautifulSoup(session.get(website).content, "lxml")
    reportId = soup.find_all(attrs={"class": "rprtid"})
    ids = [d.find_all('dd') for d in reportId]
    geoId = [geo for geo in (d[0].text.strip() for d in ids) if 'GSE' in geo]
    print(pId, geoId)
    return geoId


def getPMIDDF(pubmedIds, csbcGrants, csbcView):
    """

    :param pubmedIds:
    :param csbcGrants:
    :param csbcView:
    :return:
    """

    rows = []
    columns = ['CSBC PSON Center', 'Consortium', 'PubMed', 'Journal', 'Publication Year', 'Title', 'Authors', 'Grant',
               'Data Location', 'Synapse Location', 'Keywords']

    print("Number of publications found in pubmed query: %s" % len(pubmedIds))

    for p in pubmedIds:
        website = 'https://www.ncbi.nlm.nih.gov/pubmed/?term=%s' % p
        session = requests.Session()
        soup = BeautifulSoup(session.get(website).content, "lxml")
        # print(soup.prettify())

        title = soup.find_all(attrs={"class": "rprt abstract"})
        title = title[0].h1.string.encode('ascii', 'ignore').decode('ascii')
        title = title.replace(".", "")

        journal = soup.find_all(attrs={"class": "cit"})
        journal = journal[0].a.string
        journal = journal.replace(".", "")

        citation = soup.find_all(attrs={"class": "cit"})[0].get_text()
        print(citation)

        try:
            date = citation[1 + citation.index('.'):citation.index(';')].split()
        except:
            pass

        if date is None:
            try:
                date = citation[1 + citation.index('.'):citation.index('.')].split()

            except:
                pass

        # print(date, type(date))
        # Not all pulications hold a full date YYYY-MM-DD, some only have a year or a year and month documented.

        if len(date) == 1:
            year = date[0]
            month = 1
            day = 1
        elif len(date) == 2:
            year = date[0]
            if len(date[1]) > 3:
                # date[1] = month[0:3]
                # month = datetime.datetime.strptime(date[1], '%b').month
                month = 1
            else:
                month = datetime.datetime.strptime(date[1], '%b').month
            day = 1
        else:
            year = date[0]
            if len(date[1]) > 3:
                # date[1] = month[0:3]
                # month = datetime.datetime.strptime(date[1], '%b').month
                month = 1
            else:
                month = datetime.datetime.strptime(date[1], '%b').month
            day = date[2]

        publishedDateUTC = datetime.date(int(year), int(month), int(day)).strftime('%Y-%m-%d')
        # year = publishedDateUTC
        # .strftime("%s") and year = "/".join([str(day), str(month), str(year)]) does not currently work

        year = str(date[0])

        auths = [a.contents[0].encode('ascii', 'ignore').decode('ascii') for a in
                 soup.find('div', attrs={"class": "auths"}).findAll('a')]

        if len(auths) > 1:
            auths = ', '.join(auths)
        else:
            auths = auths[0]

        # example output is a list of 'U54 CA209997/CA/NCI NIH HHS/United States'
        grants = [g.contents[0] for g in soup.find('div', attrs={"class": "rprt_all"}).findAll('a', attrs={
            "abstractlink": "yes", "alsec": "grnt"})]

        grants = [g for g in grants if any(x in g for x in ['U54', 'U01'])]

        cleangrants = []

        for g in grants:
            # if the grant string split lengths are not within these standard lengths (smaller or larger)
            # then the grant number and grant synapse Id has to be double checked and added to table manually.

            if len(g.split()) == 4 and g.startswith('U'):
                g = g[:3] + ' ' + g[3:]
                if "-" in g:
                    g = re.sub('-', '', g)

                if ' ' not in g.split("/")[0]:
                    g = g[:3] + ' ' + g[3:]
                cleangrants.append(g)

            if len(g.split()) == 5 and g.startswith('U'):
                if "-" in g:
                    g = re.sub('-', '', g)

                if ' ' not in g.split("/")[0]:
                    g = g[:3] + ' ' + g[3:]

                if '/' not in g.split()[1] and '/' in g.split()[2]:
                    g = ' '.join([grants[0].split()[0], ''.join(grants[0].split()[1:3]), grants[0].split()[3],
                              grants[0].split()[4]])

                cleangrants.append(g)

        grants = list(set(cleangrants))

        print(grants)

        if grants:

            gnum = [g.split()[1][:g.split()[1].index("/")] for g in grants]
            index = [j for j, x in enumerate(gnum) if
                     x in csbcGrants]

            if index:

                gType = [grants[i].split()[0] for i in index]
                gNumber = [grants[i].split()[1][:g.split()[1].index("/")] for i in index]
                print(gNumber)
                csbcgrant = [' '.join(e) for e in zip(gType, gNumber)]

                # match and get the csbc center synapse id from it's view table by grant number of this journal study
                centerSynId = csbcView.loc[csbcView['grantNumber'].isin(gNumber)].id.iloc[0]
                consortium = ','.join(list(set(csbcView.loc[csbcView['grantNumber'].isin(gNumber)].consortium)))

                if len(csbcgrant) > 1:
                    csbcgrant = ', '.join(csbcgrant)
                else:
                    csbcgrant = csbcgrant[0]
            else:
                csbcgrant = ""
                centerSynId = ""

        else:
            csbcgrant = ""
            centerSynId = ""

        gseIds = getPublishedGEO(p)

        if len(gseIds) > 1:
            gseIds = ['https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=' + s for s in gseIds]
            gseIds = ' , '.join(gseIds)

        elif len(gseIds) == 1:
            gseIds = 'https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=' + gseIds[0]
        else:
            gseIds = ''

        rowDf = pandas.DataFrame(
            [[centerSynId, consortium, website, journal, year, title, auths, csbcgrant, gseIds, 'No', '']], columns=columns)
        rows.append(rowDf)

    tableDf = pandas.concat(rows)
    return tableDf


def pubmed(args, syn):
    """
    Given a list of grant numbers pulled from a synapse table column, utilizes a pubmed API to generate a search query.
    This query is constructed by the union ('or' logic) of all the grant numbers, which would aid in pulling down a list
    of all PubMed publication id's associated with the grants. Then it will go through the PubMed id's and scrape the
    publication for basic informative information.

    :param args:
    :param syn:
    :return:
    """
    projectId = args.projectId
    project = syn.get(projectId)

    if args.grantviewId is not None:
        grantviewId = args.grantviewId
    else:
        grantviewId = "syn10142562"

    csbcGrants = csbcGrantList(syn, grantviewId)
    grantIds = getGrantQuery(csbcGrants)
    pubmedIds = getPubMedIds(grantIds)
    csbcView = getCenterIdsView(syn, grantviewId)

    # for utf encoding and debugging
    # finalTable.to_csv("csbc.csv", sep=',', index=False, encoding="utf-8")
    # finalTable = pandas.read_csv("csbc.csv", delimiter=',', encoding="utf-8")
    # os.remove("csbc.csv")

    if args.tableId:
        # update existing schema
        tableId = args.tableId
        schema = syn.get(tableId)

        publicationTable = syn.tableQuery("select * from %s" % tableId)
        currentTable = publicationTable.asDataFrame()

        new_pubmed_ids = list(set(pubmedIds) - set([i.split("=")[1] for i in list(currentTable.PubMed)]))
        finalTable = getPMIDDF(new_pubmed_ids, csbcGrants, csbcView)

        if not currentTable.empty:
            # extract new rows in final table to append to synapse table
            finalTable = pandas.merge(finalTable, currentTable, on=["PubMed"], how='outer', indicator=True).query(
                '_merge == "left_only"')

            if finalTable.empty:
                print("nothing to update")
            else:
                # append new rows
                table = synapseclient.Table(schema, finalTable.values.tolist())
                table = syn.store(table)
        else:
            # add new rows
            table = synapseclient.Table(schema, finalTable.values.tolist())
            table = syn.store(table)

    else:
        # create a new schema
        # cols = synapseclient.as_table_columns(finalTable)
        finalTable = getPMIDDF(pubmedIds, csbcGrants, csbcView)

        cols = [Column(name='CSBC PSON Center', columnType='ENTITYID', maximumSize=50),
                Column(name='Consortium', columnType='STRING', maximumSize=100),
                Column(name='PubMed', columnType='LINK', maximumSize=100),
                Column(name='Journal', columnType='STRING', maximumSize=100),
                Column(name='Publication Year', columnType='DATE'),
                Column(name='Title', columnType='STRING', maximumSize=500),
                Column(name='Authors', columnType='STRING', maximumSize=990),
                Column(name='Grant', columnType='STRING', maximumSize=50),
                Column(name='Data Location', columnType='LINK', maximumSize=1000),
                Column(name='Synapse Location', columnType='STRING', maximumSize=10),
                Column(name='Keywords', columnType='STRING', maximumSize=250)]

        schema = synapseclient.Schema(name=args.tableName, columns=cols, parent=project)
        table = synapseclient.Table(schema, finalTable)
        table = syn.store(table)


def buildParser():
    """

    :return:
    """
    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers(title='commands',
                                       description='The following commands are available:',
                                       help='For additional help: "csbc <COMMAND> -h"')

    parser_template = subparsers.add_parser('template', help='Create consortium template for new projects')

    parser_template.add_argument('--consortiumId', help='Consortium grant id ex. U54', required=True, type=str)
    parser_template.add_argument('--projectName', help='Consortium project name title', required=True, type=str)
    parser_template.add_argument('--teamId', help='Consortium project synapse team id ex. 3346139', type=str)

    parser_template.set_defaults(func=template)

    parser_pubmed = subparsers.add_parser('pubmed', help='Scrape pubMed publication information based on consortium '
                                                         'grant number')

    parser_pubmed.add_argument('--projectId', help='Synapse project to create the data policy table', required=True,
                               type=str)
    parser_pubmed.add_argument('--grantviewId', help='A table synapse id containing the grantNumber field',
                               required=True, type=str)
    parser_pubmed.add_argument('--tableName', help='Synapse table name that would hold pubmed scrape info', type=str)
    parser_pubmed.add_argument('--tableId', help='Synapse table id that holds the pubmed scrape info', type=str)

    parser_pubmed.set_defaults(func=pubmed)

    return parser


def _csbc_error_msg(ex):
    """
    Format a human readable error message

    :param ex:
    :return:
    """
    if isinstance(ex, six.string_types):
        return ex

    return '\n' + ex.__class__.__name__ + ': ' + str(ex) + '\n\n'


def performMain(args, syn):
    """
    Format a human readable error message

    :param args:
    :param syn:
    :return:
    """
    if 'func' in args:
        try:
            args.func(args, syn)
        except Exception as ex:
            if args.debug:
                raise
            else:
                sys.stderr.write(_csbc_error_msg(ex))


def main():
    args = buildParser().parse_args()
    syn = synapseLogin()

    performMain(args, syn)


if __name__ == "__main__":
    main()