import os
import shutil

from datalake_library.commons import init_logger
from datalake_library.transforms.transform_handler import TransformHandler
from datalake_library import octagon
from datalake_library.octagon import Artifact, EventReasonEnum, peh
from datalake_library.configuration.resource_configs import DynamoConfiguration
from datalake_library.interfaces.dynamo_interface import DynamoInterface

logger = init_logger(__name__)
dynamo_config = DynamoConfiguration()
dynamo_interface = DynamoInterface(dynamo_config)

def remove_content_tmp():
    # Remove contents of the Lambda /tmp folder (Not released by default)
    for root, dirs, files in os.walk('/tmp'):
        for f in files:
            os.unlink(os.path.join(root, f))
        for d in dirs:
            shutil.rmtree(os.path.join(root, d))


def lambda_handler(event, context):
    """Calls custom transform developed by user

    Arguments:
        event {dict} -- Dictionary with details on previous processing step
        context {dict} -- Dictionary with details on Lambda context

    Returns:
        {dict} -- Dictionary with Processed Bucket and Key(s)
    """
    try:
        logger.info('Fetching event data from previous step')
        bucket = event['body']['bucket']
        key = event['body']['key']
        team = event['body']['team']
        stage = event['body']['pipeline_stage']
        dataset = event['body']['dataset']
        ddb_key = event['body']['manifest_ddb_key']

        logger.info('Initializing Octagon client')
        component = context.function_name.split('-')[-2].title()
        octagon_client = (
            octagon.OctagonClient()
            .with_run_lambda(True)
            .with_configuration_instance(event['body']['env'])
            .build()
        )
        peh.PipelineExecutionHistoryAPI(
            octagon_client).retrieve_pipeline_execution(event['body']['peh_id'])

        # Call custom transform created by user and process the file
        logger.info('Calling user custom processing code')
        transform_handler = TransformHandler().stage_transform(team, dataset, stage)
        response = transform_handler().transform_object(
            bucket, key, team, dataset)  # custom user code called
        remove_content_tmp()
        octagon_client.update_pipeline_execution(status="{} {} Processing".format(stage, component),
                                                 component=component)
        dynamo_interface.update_manifests_control_table_stagea(
            ddb_key,"PROCESSING",response[0])
    except Exception as e:
        logger.error("Fatal error", exc_info=True)
        octagon_client.end_pipeline_execution_failed(component=component,
                                                     issue_comment="{} {} Error: {}".format(stage, component, repr(e)))
        remove_content_tmp()
        dynamo_interface.update_manifests_control_table_stagea(
            ddb_key, "FAILED")
        raise e
    return response
